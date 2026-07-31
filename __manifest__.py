# -*- coding: utf-8 -*-
{
    'name': 'Import Lot Allocation',
    'version': '16.0.6.0.0',
    'summary': 'Commercial import allocation, stock rework, and planned delivery packages',
    'description': '''
Import Lot Allocation
=====================

Adds an Import Lot layer to group incoming supply from purchase orders and allocate it commercially to sale order lines.

Important: Import Lots are commercial/supply references. Incoming receipts can create Import Lot packages,
while Sale Order lines select an existing Import Lot. The internal delivery plan is created automatically,
and the physical stock.quant.package is created only when the delivery is completed.

Future package references reserve the Purchase Order number before receipt, and Rework Orders group
multiple product conversions for one Sale Order while keeping each result in its purchased source package.
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
        'views/stock_expected_package_views.xml',
        'views/purchase_order_views.xml',
        'views/stock_rework_views.xml',
        'views/sale_order_views.xml',
        'views/stock_picking_views.xml',
    ],
    'installable': True,
    'application': True,
}
