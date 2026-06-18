# -*- coding: utf-8 -*-
{
    'name': 'Import Lot Allocation',
    'version': '16.0.2.1.0',
    'summary': 'Commercial allocation of incoming import lots to sales',
    'description': '''
Import Lot Allocation
=====================

Adds an Import Lot layer to group incoming supply from purchase orders and allocate it commercially to sale order lines.

Important: this module does not replace Odoo stock lots (stock.lot), packages, quants, or physical reservations. Import Lots are commercial/supply references used for planning and validation at delivery time.
''',
    'category': 'Inventory/Inventory',
    'author': 'OpenAI - ChatGPT',
    'license': 'LGPL-3',
    'depends': ['sale_stock', 'purchase_stock', 'mail'],
    'data': [
        'security/import_lot_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence.xml',
        'views/import_lot_views.xml',
        'views/purchase_order_views.xml',
        'views/sale_order_views.xml',
        'views/stock_picking_views.xml',
    ],
    'installable': True,
    'application': True,
}
