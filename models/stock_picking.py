# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


class StockMove(models.Model):
    _inherit = 'stock.move'

    planned_sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order for Planned Package',
        related='sale_line_id.order_id',
        store=True,
        index=True,
        readonly=True,
    )
    planned_package_id = fields.Many2one(
        'stock.package.plan',
        string='Planned Package',
        check_company=True,
        copy=True,
        index=True,
        help=(
            'Delivery package plan copied from the Sale Order line. '
            'A physical package is created when the move is done.'
        ),
    )
    planned_import_lot_id = fields.Many2one(
        'import.lot',
        string='Import Lot',
        related='planned_package_id.import_lot_id',
        store=True,
        readonly=True,
        index=True,
        help='Import Lot selected on the source Sale Order line.',
    )
    planned_source_package_id = fields.Many2one(
        'stock.quant.package',
        string='Source Package',
        related='planned_package_id.source_package_id',
        store=True,
        readonly=True,
        index=True,
        help='Physical source package supplied by the selected Import Lot or Rework.',
    )
    # Kept for backward compatibility with the previous package-per-line version.
    package_id = fields.Many2one(
        'stock.quant.package',
        string='Legacy Source Package',
        copy=False,
        help='Deprecated physical source package field kept for existing records.',
    )

    def _prepare_move_split_vals(self, qty):
        vals = super()._prepare_move_split_vals(qty)
        if self.planned_package_id:
            vals['planned_package_id'] = self.planned_package_id.id
        return vals

    @api.constrains('planned_package_id', 'sale_line_id')
    def _check_planned_package_sale_order(self):
        for move in self:
            if (
                move.planned_package_id
                and move.sale_line_id
                and move.planned_package_id.sale_order_id != move.sale_line_id.order_id
            ):
                raise ValidationError(_(
                    'The planned package on a stock move must belong to its Sale Order.'
                ))

    def _assign_physical_packages_from_plans(self):
        """Create one destination package per plan and completed picking.

        A partial delivery creates a backorder picking. Because the plan is copied to the
        split move, validating that backorder later creates another physical package.
        """
        grouped_lines = {}
        for move in self.filtered(
            lambda record: record.state not in ('done', 'cancel')
            and record.picking_type_id.code == 'outgoing'
            and record.planned_package_id
        ):
            done_lines = move.move_line_ids.filtered(lambda line: line.qty_done > 0)
            if not done_lines:
                continue
            key = (move.planned_package_id.id, move.picking_id.id)
            grouped_lines[key] = grouped_lines.get(key, self.env['stock.move.line']) | done_lines

        Package = self.env['stock.quant.package']
        for (plan_id, picking_id), move_lines in grouped_lines.items():
            plan = self.env['stock.package.plan'].browse(plan_id)
            picking = self.env['stock.picking'].browse(picking_id)
            result_packages = move_lines.mapped('result_package_id')

            if result_packages:
                valid_existing_package = (
                    len(result_packages) == 1
                    and result_packages.planned_package_id == plan
                    and result_packages.planned_picking_id == picking
                )
                if not valid_existing_package:
                    raise UserError(_(
                        'Transfer %(picking)s contains manually assigned destination packages for planned package '
                        '%(plan)s. Remove those destination packages before validating the transfer.'
                    ) % {
                        'picking': picking.name,
                        'plan': plan.name,
                    })
                physical_package = result_packages
            else:
                physical_package = Package.search([
                    ('planned_package_id', '=', plan.id),
                    ('planned_picking_id', '=', picking.id),
                ], limit=1)
                if not physical_package:
                    physical_package = Package.create({
                        'name': '%s / %s' % (plan.name, picking.name),
                        'package_type_id': plan.package_type_id.id or False,
                        'planned_package_id': plan.id,
                        'planned_picking_id': picking.id,
                    })

            move_lines.filtered(
                lambda line: line.result_package_id != physical_package
            ).write({'result_package_id': physical_package.id})

    def _get_planned_source_package_available_qty(self):
        """Return usable quantity in the plan's source package, including this move's reservation."""
        self.ensure_one()
        source_package = self.planned_package_id.source_package_id
        if not source_package:
            return 0.0

        available_product_uom = self.env['stock.quant']._get_available_quantity(
            self.product_id,
            self.location_id,
            package_id=source_package,
            strict=False,
        )
        available_move_uom = self.product_id.uom_id._compute_quantity(
            available_product_uom,
            self.product_uom,
            round=False,
        )
        reserved_by_move = sum(
            line.product_uom_id._compute_quantity(
                line.reserved_uom_qty,
                self.product_uom,
                round=False,
            )
            for line in self.move_line_ids.filtered(
                lambda move_line: move_line.package_id == source_package
            )
        )
        return available_move_uom + reserved_by_move

    def _action_done(self, cancel_backorder=False):
        plans = self.mapped('planned_package_id')
        self._assign_physical_packages_from_plans()
        result = super()._action_done(cancel_backorder=cancel_backorder)
        plans._compute_state()
        return result


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    import_lot_id = fields.Many2one(
        'import.lot',
        string='Import Lot',
        index=True,
        tracking=True,
        help='Supply/import lot related to this receipt or transfer. This is not the standard Odoo stock lot.',
    )

    def button_validate(self):
        # For incoming receipts, put all received products into a package named as the Import Lot.
        self._assign_import_lot_package_on_receipt()
        # For outgoing deliveries, prepare quantities while keeping the package virtual.
        self._check_planned_source_package_delivery_rules()
        self._prepare_planned_packages_on_delivery()
        # Preserve the previous behavior only for open records that still use the legacy field.
        self._assign_legacy_source_packages_on_delivery()
        self._check_legacy_source_package_delivery_rules()
        res = super().button_validate()
        self._update_import_lot_after_receipt()
        return res

    def _get_or_create_import_lot_package(self, import_lot, company):
        Package = self.env['stock.quant.package']
        package = Package.search([
            ('name', '=', import_lot.name),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', company.id),
        ], limit=1)
        if not package:
            package = Package.create({
                'name': import_lot.name,
                'company_id': company.id,
            })
        return package

    def _get_move_qty_to_process(self, move):
        qty = move.quantity_done or 0.0
        if not qty:
            qty = move.product_uom_qty or 0.0
        return qty

    def _assign_import_lot_package_on_receipt(self):
        """Use the Import Lot reference as the physical package on receipts."""
        MoveLine = self.env['stock.move.line']
        for picking in self.filtered(lambda p: p.picking_type_code == 'incoming' and p.import_lot_id):
            package = self._get_or_create_import_lot_package(picking.import_lot_id, picking.company_id)
            for move in picking.move_ids_without_package.filtered(
                lambda record: record.product_id and record.product_id.detailed_type == 'product'
            ):
                qty_to_receive = self._get_move_qty_to_process(move)
                if not qty_to_receive:
                    continue

                if not move.move_line_ids:
                    MoveLine.create({
                        'picking_id': picking.id,
                        'move_id': move.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        'qty_done': qty_to_receive,
                        'result_package_id': package.id,
                        'company_id': picking.company_id.id,
                    })
                    continue

                remaining_qty = qty_to_receive
                for move_line in move.move_line_ids.filtered(lambda ml: ml.product_id == move.product_id):
                    if not move_line.qty_done:
                        qty_line = getattr(move_line, 'reserved_uom_qty', 0.0) or remaining_qty
                        move_line.qty_done = qty_line
                    if not move_line.result_package_id:
                        move_line.result_package_id = package.id
                    remaining_qty -= move_line.qty_done

                if float_compare(remaining_qty, 0.0, precision_rounding=move.product_uom.rounding or 0.01) > 0:
                    MoveLine.create({
                        'picking_id': picking.id,
                        'move_id': move.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        'qty_done': remaining_qty,
                        'result_package_id': package.id,
                        'company_id': picking.company_id.id,
                    })

    def _assign_legacy_source_packages_on_delivery(self):
        """Keep pre-upgrade open deliveries functional without exposing this flow to new sales."""
        MoveLine = self.env['stock.move.line']
        for picking in self.filtered(lambda record: record.picking_type_code == 'outgoing'):
            legacy_moves = picking.move_ids_without_package.filtered(
                lambda move: move.product_id
                and move.product_id.detailed_type == 'product'
                and move.package_id
                and not move.planned_package_id
            )
            for move in legacy_moves:
                qty_to_deliver = self._get_move_qty_to_process(move)
                if not qty_to_deliver:
                    continue

                if not move.move_line_ids:
                    MoveLine.create({
                        'picking_id': picking.id,
                        'move_id': move.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        'qty_done': qty_to_deliver,
                        'package_id': move.package_id.id,
                        'company_id': picking.company_id.id,
                    })
                    continue

                remaining_qty = qty_to_deliver
                for move_line in move.move_line_ids.filtered(lambda line: line.product_id == move.product_id):
                    if not move_line.qty_done:
                        qty_line = getattr(move_line, 'reserved_uom_qty', 0.0) or remaining_qty
                        move_line.qty_done = qty_line
                    if not move_line.package_id:
                        move_line.package_id = move.package_id.id
                    remaining_qty -= move_line.qty_done

                if float_compare(
                    remaining_qty,
                    0.0,
                    precision_rounding=move.product_uom.rounding or 0.01,
                ) > 0:
                    MoveLine.create({
                        'picking_id': picking.id,
                        'move_id': move.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        'qty_done': remaining_qty,
                        'package_id': move.package_id.id,
                        'company_id': picking.company_id.id,
                    })

    def _check_legacy_source_package_delivery_rules(self):
        Quant = self.env['stock.quant']
        for picking in self.filtered(lambda record: record.picking_type_code == 'outgoing'):
            errors = []
            legacy_moves = picking.move_ids_without_package.filtered(
                lambda move: move.product_id
                and move.product_id.detailed_type == 'product'
                and move.package_id
                and not move.planned_package_id
            )
            for move in legacy_moves:
                qty_to_deliver = self._get_move_qty_to_process(move)
                if not qty_to_deliver:
                    continue
                available_qty_product_uom = Quant._get_available_quantity(
                    move.product_id,
                    move.location_id,
                    package_id=move.package_id,
                    strict=False,
                )
                available_qty = move.product_id.uom_id._compute_quantity(
                    available_qty_product_uom,
                    move.product_uom,
                    rounding_method='HALF-UP',
                )
                precision = move.product_uom.rounding or 0.01
                if float_compare(available_qty, qty_to_deliver, precision_rounding=precision) < 0:
                    errors.append(_(
                        '- %(product)s: delivery quantity %(delivery_qty)s %(uom)s, available in package '
                        '%(package)s at the source location: %(available)s %(uom)s.'
                    ) % {
                        'product': move.product_id.display_name,
                        'delivery_qty': qty_to_deliver,
                        'available': available_qty,
                        'package': move.package_id.name,
                        'uom': move.product_uom.name,
                    })
            if errors:
                raise UserError(_(
                    'Some legacy source packages do not have enough available stock.\n\n%(details)s'
                ) % {'details': '\n'.join(errors)})

    def _prepare_planned_packages_on_delivery(self):
        """Prepare done quantities without creating the physical package yet.

        The physical package is created by ``stock.move._action_done`` only after Odoo's
        immediate-transfer and backorder checks have completed.
        """
        MoveLine = self.env['stock.move.line']
        for picking in self.filtered(lambda p: p.picking_type_code == 'outgoing'):
            for move in picking.move_ids_without_package.filtered(
                lambda record: record.product_id
                and record.product_id.detailed_type == 'product'
                and record.planned_package_id
            ):
                qty_to_deliver = self._get_move_qty_to_process(move)
                if not qty_to_deliver:
                    continue
                source_package = move.planned_package_id.source_package_id

                if not move.move_line_ids:
                    MoveLine.create({
                        'picking_id': picking.id,
                        'move_id': move.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        'qty_done': qty_to_deliver,
                        'package_id': source_package.id if source_package else False,
                        'company_id': picking.company_id.id,
                    })
                    continue

                remaining_qty = qty_to_deliver
                for move_line in move.move_line_ids.filtered(lambda ml: ml.product_id == move.product_id):
                    if not move_line.qty_done:
                        qty_line = getattr(move_line, 'reserved_uom_qty', 0.0) or remaining_qty
                        move_line.qty_done = qty_line
                    if source_package and move_line.package_id != source_package:
                        move_line.package_id = source_package.id
                    remaining_qty -= move_line.qty_done

                if float_compare(remaining_qty, 0.0, precision_rounding=move.product_uom.rounding or 0.01) > 0:
                    MoveLine.create({
                        'picking_id': picking.id,
                        'move_id': move.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        'qty_done': remaining_qty,
                        'package_id': source_package.id if source_package else False,
                        'company_id': picking.company_id.id,
                    })

    def _check_planned_source_package_delivery_rules(self):
        for picking in self.filtered(lambda record: record.picking_type_code == 'outgoing'):
            errors = []
            planned_moves = picking.move_ids_without_package.filtered(
                lambda move: move.product_id
                and move.product_id.detailed_type == 'product'
                and move.planned_package_id
            )
            for move in planned_moves:
                qty_to_deliver = self._get_move_qty_to_process(move)
                if not qty_to_deliver:
                    continue
                source_package = move.planned_package_id.source_package_id
                if (
                    move.planned_package_id.import_lot_id.rework_order_ids
                    and not source_package
                ):
                    errors.append(_(
                        '- %(product)s: Import Lot %(lot)s does not have a physical source package yet. '
                        'Complete its purchase receipt or Rework first.'
                    ) % {
                        'product': move.product_id.display_name,
                        'lot': move.planned_package_id.import_lot_id.name,
                    })
                    continue
                if not source_package:
                    continue
                available_qty = move._get_planned_source_package_available_qty()
                if float_compare(
                    available_qty,
                    qty_to_deliver,
                    precision_rounding=move.product_uom.rounding or 0.01,
                ) < 0:
                    errors.append(_(
                        '- %(product)s: delivery quantity %(delivery_qty)s %(uom)s, available in source package '
                        '%(package)s: %(available)s %(uom)s.'
                    ) % {
                        'product': move.product_id.display_name,
                        'delivery_qty': qty_to_deliver,
                        'available': available_qty,
                        'package': source_package.name,
                        'uom': move.product_uom.name,
                    })
            if errors:
                raise UserError(_(
                    'Some planned source packages do not have enough available stock.\n\n%(details)s'
                ) % {'details': '\n'.join(errors)})

    def _update_import_lot_after_receipt(self):
        for picking in self.filtered(lambda p: p.picking_type_code == 'incoming' and p.import_lot_id):
            lot = picking.import_lot_id
            if lot.state not in ('closed', 'cancelled'):
                if all(line.received_qty >= line.expected_qty for line in lot.line_ids):
                    lot.state = 'received'
                elif any(line.received_qty > 0 for line in lot.line_ids):
                    lot.state = 'partially_received'
