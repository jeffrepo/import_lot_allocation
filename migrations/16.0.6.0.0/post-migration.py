# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # Reserve the PO-numbered future package for Import Lots created by older
    # module versions. The physical package is still created only when needed.
    import_lots = env['import.lot'].search([
        ('purchase_order_id', '!=', False),
    ])
    expected_packages = import_lots._ensure_expected_package()
    for expected in expected_packages:
        receipt_packages = expected.import_lot_ids.mapped(
            'picking_ids.move_line_ids.result_package_id'
        )
        source_packages = expected.import_lot_ids.mapped('source_package_id')
        if len(receipt_packages | source_packages) == 1:
            expected._get_or_create_physical_package()

    # Preserve existing single-conversion Reworks in the new multi-line UI.
    env['stock.rework.order'].search([])._ensure_line_records()
