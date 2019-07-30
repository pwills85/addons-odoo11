# -*- coding: utf-8 -*-
from odoo import api, models, fields
from odoo.tools.translate import _
from odoo.exceptions import UserError
from .bigint import BigInt
import logging
_logger = logging.getLogger(__name__)


class account_move(models.Model):
    _inherit = "account.move"

    document_class_id = fields.Many2one(
            'sii.document_class',
            string='Document Type',
            copy=False,
            readonly=True,
            states={'draft': [('readonly', False)]},
        )
    sii_document_number = BigInt(
            string='Document Number',
            copy=False,
            readonly=True,
            states={'draft': [('readonly', False)]},
        )
    canceled = fields.Boolean(
            string="Canceled?",
            readonly=True,
            states={'draft': [('readonly', False)]},
        )
    iva_uso_comun = fields.Boolean(
            string="Iva Uso Común",
            readonly=True,
            states={'draft': [('readonly', False)]},
        )
    no_rec_code = fields.Selection(
            [
                ('1','Compras destinadas a IVA a generar operaciones no gravados o exentas.'),
                ('2','Facturas de proveedores registrados fuera de plazo.'),
                ('3','Gastos rechazados.'),
                ('4','Entregas gratuitas (premios, bonificaciones, etc.) recibidos.'),
                ('9','Otros.')
            ],
            string="Código No recuperable",
            readonly=True,
            states={'draft': [('readonly', False)]},
        )# @TODO select 1 automático si es emisor 2Categoría
    sended = fields.Boolean(
            string="Enviado al SII",
            default=False,
            readonly=True,
            states={'draft': [('readonly', False)]},
        )
    factor_proporcionalidad = fields.Float(
            string="Factor proporcionalidad",
            default=0.00,
            readonly=True,
            states={'draft': [('readonly', False)]},
        )

    def _get_move_imps(self):
        imps = {}
        for l in self.line_ids:
            if l.tax_line_id:
                if l.tax_line_id:
                    if not l.tax_line_id.id in imps:
                        imps[l.tax_line_id.id] = {'tax_id':l.tax_line_id.id, 'credit':0 , 'debit': 0, 'code':l.tax_line_id.sii_code}
                    imps[l.tax_line_id.id]['credit'] += l.credit
                    imps[l.tax_line_id.id]['debit'] += l.debit
                    if l.tax_line_id.activo_fijo:
                        ActivoFijo[1] += l.credit
            elif l.tax_ids and l.tax_ids[0].amount == 0: #caso monto exento
                if not l.tax_ids[0].id in imps:
                    imps[l.tax_ids[0].id] = {'tax_id':l.tax_ids[0].id, 'credit':0 , 'debit': 0, 'code':l.tax_ids[0].sii_code}
                imps[l.tax_ids[0].id]['credit'] += l.credit
                imps[l.tax_ids[0].id]['debit'] += l.debit
        return imps

    def totales_por_movimiento(self):
        move_imps = self._get_move_imps()
        imps = {'iva':0,
                'exento':0,
                'otros_imps':0,
                }
        for key, i in move_imps.items():
            if i['code'] in [14]:
                imps['iva']  += (i['credit'] or i['debit'])
            elif i['code'] == 0:
                imps['exento']  += (i['credit'] or i['debit'])
            else:
                imps['otros_imps']  += (i['credit'] or i['debit'])
        imps['neto'] = self.amount - imps['otros_imps'] - imps['exento'] - imps['iva']
        return imps


class account_move_line(models.Model):
    _inherit = "account.move.line"

    document_class_id = fields.Many2one(
            'sii.document_class',
            string='Document Type',
            related='move_id.document_class_id',
            store=True,
            readonly=True,
        )


class account_journal(models.Model):
    _inherit = "account.journal"

    sucursal_id = fields.Many2one(
            'sii.sucursal',
            string="Sucursal",
        )
    sii_code = fields.Char(
            related='sucursal_id.name',
            string="Código SII Sucursal",
            readonly=True,
        )
    journal_document_class_ids = fields.One2many(
            'account.journal.sii_document_class',
            'journal_id',
            'Documents Class',
        )
    use_documents = fields.Boolean(
            string='Use Documents?',
            default='_get_default_doc',
        )
    company_activity_ids = fields.Many2many(
        'partner.activities',
        related='company_id.company_activities_ids'
    )
    journal_activities_ids = fields.Many2many(
            'partner.activities',
            id1='journal_id',
            id2='activities_id',
            string='Journal Turns',
            help="""Select the turns you want to \
            invoice in this Journal""",
        )
    restore_mode = fields.Boolean(
            string="Restore Mode",
            default=False,
        )

    @api.onchange('journal_activities_ids')
    def max_actecos(self):
        if len(self.journal_activities_ids) > 4:
            raise UserError("Deben Ser máximo 4 actecos por Diario, seleccione los más significativos para este diario")

    @api.multi
    def _get_default_doc(self):
        self.ensure_one()
        if self.type == 'sale' or self.type == 'purchase':
            self.use_documents = True

    @api.multi
    def name_get(self):
        res = []
        for journal in self:
            currency = journal.currency_id or journal.company_id.currency_id
            name = "%s (%s)" % (journal.name, currency.name)
            if journal.sucursal_id and self.env.context.get('show_full_name', False):
                name = "%s (%s)" % (name, journal.sucursal_id.name)
            res.append((journal.id, name))
        return res
