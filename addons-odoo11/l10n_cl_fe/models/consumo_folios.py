# -*- coding: utf-8 -*-
from odoo import fields, models, api, tools
from odoo.tools.translate import _
from odoo.exceptions import UserError
from datetime import datetime, timedelta
import dateutil.relativedelta as relativedelta
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT as DTF
import logging
from lxml import etree
from lxml.etree import Element, SubElement
import pytz
import collections
try:
    import xmltodict
except ImportError:
    _logger.info('Cannot import xmltodict library')
try:
    import dicttoxml
    dicttoxml.set_debug(False)
except ImportError:
    _logger.info('Cannot import dicttoxml library')


class ConsumoFolios(models.Model):
    _name = "account.move.consumo_folios"

    sii_xml_request = fields.Many2one(
            'sii.xml.envio',
            string='SII XML Request',
            copy=False,
            readonly=True,
            states={'draft': [('readonly', False)]},)
    state = fields.Selection([
            ('draft', 'Borrador'),
            ('NoEnviado', 'No Enviado'),
            ('EnCola', 'En Cola'),
            ('Enviado', 'Enviado'),
            ('Aceptado', 'Aceptado'),
            ('Rechazado', 'Rechazado'),
            ('Reparo', 'Reparo'),
            ('Proceso', 'Proceso'),
            ('Reenviar', 'Reenviar'),
            ('Anulado', 'Anulado')],
        string='Resultado',
        index=True,
        readonly=True,
        default='draft',
        track_visibility='onchange',
        copy=False,
        help=" * The 'Draft' status is used when a user is encoding a new and unconfirmed Invoice.\n"
             " * The 'Pro-forma' status is used the invoice does not have an invoice number.\n"
             " * The 'Open' status is used when user create invoice, an invoice number is generated. Its in open status till user does not pay invoice.\n"
             " * The 'Paid' status is set automatically when the invoice is paid. Its related journal entries may or may not be reconciled.\n"
             " * The 'Cancelled' status is used when user cancel invoice.")
    move_ids = fields.Many2many(
        'account.move',
    	readonly=True,
        states={'draft': [('readonly', False)]},)
    fecha_inicio = fields.Date(
            string="Fecha Inicio",
            readonly=True,
            states={'draft': [('readonly', False)]},
            default=lambda self: fields.Date.context_today(self),
        )
    fecha_final = fields.Date(
            string="Fecha Final",
            readonly=True,
            states={'draft': [('readonly', False)]},
            default=lambda self: fields.Date.context_today(self),
        )
    correlativo = fields.Integer(
            string="Correlativo",
            readonly=True,
            states={'draft': [('readonly', False)]},
            invisible=True,
        )
    sec_envio = fields.Integer(
            string="Secuencia de Envío",
            readonly=True,
            states={'draft': [('readonly', False)]},
        )
    total_neto = fields.Monetary(
        string="Total Neto",
        store=True,
        readonly=True,
        compute='get_totales',)
    total_iva = fields.Monetary(
        string="Total Iva",
        store=True,
        readonly=True,
        compute='get_totales',)
    total_exento = fields.Monetary(
        string="Total Exento",
        store=True,
        readonly=True,
        compute='get_totales',)
    total = fields.Monetary(
        string="Monto Total",
        store=True,
        readonly=True,
        compute='get_totales',)
    total_boletas = fields.Integer(
        string="Total Boletas",
        store=True,
        readonly=True,
        compute='get_totales',)
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.user.company_id.id,
    	readonly=True,
        states={'draft': [('readonly', False)]},)
    name = fields.Char(
        string="Detalle" ,
        required=True,
    	readonly=True,
        states={'draft': [('readonly', False)]},)
    date = fields.Date(
            string="Date",
            required=True,
        	readonly=True,
            states={'draft': [('readonly', False)]},
            default=lambda *a: datetime.now(),
        )
    detalles = fields.One2many(
        'account.move.consumo_folios.detalles',
       'cf_id',
       string="Detalle Rangos",
       readonly=True,
       states={'draft': [('readonly', False)]},)
    impuestos = fields.One2many(
        'account.move.consumo_folios.impuestos',
       'cf_id',
       string="Detalle Impuestos",
       readonly=True,
       states={'draft': [('readonly', False)]},)
    anulaciones = fields.One2many('account.move.consumo_folios.anulaciones',
        'cf_id',
        string="Detalle Impuestos",
        readonly=True,
        states={'draft': [('readonly', False)]},)
    currency_id = fields.Many2one(
            'res.currency',
            string='Moneda',
            default=lambda self: self.env.user.company_id.currency_id,
            required=True,
            track_visibility='always',
        	readonly=True,
            states={'draft': [('readonly', False)]},
        )
    responsable_envio = fields.Many2one(
            'res.users',
        )
    sii_result = fields.Selection(
            [
                ('draft', 'Borrador'),
                ('NoEnviado', 'No Enviado'),
                ('Enviado', 'Enviado'),
                ('Aceptado', 'Aceptado'),
                ('Rechazado', 'Rechazado'),
                ('Reparo', 'Reparo'),
                ('Proceso', 'Proceso'),
                ('Reenviar', 'Reenviar'),
                ('Anulado', 'Anulado')
            ],
            related="state",
        )

    _order = 'fecha_inicio desc'

    @api.model
    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        res = super(ConsumoFolios, self).read_group(domain, fields, groupby, offset, limit=limit, orderby=orderby, lazy=lazy)
        if 'total_iva' in fields:
            for line in res:
                if '__domain' in line:
                    lines = self.search(line['__domain'])
                    line.update({
                            'total_neto': 0,
                            'total_iva': 0,
                            'total_exento': 0,
                            'total': 0,
                            'total_boletas': 0,
                        })
                    for l in lines:
                        line.update({
                                'total_neto': line['total_neto'] + l.total_neto,
                                'total_iva': line['total_iva'] + l.total_iva,
                                'total_exento': line['total_exento'] + l.total_exento,
                                'total': line['total'] + l.total,
                                'total_boletas': line['total_boletas'] + l.total_boletas,
                            })
        return res

    @api.onchange('impuestos')
    @api.depends('impuestos')
    def get_totales(self):
        for r in self:
            total_iva = 0
            total_exento = 0
            total = 0
            total_boletas = 0
            for d in r.impuestos:
                total_iva += d.monto_iva
                total_exento += d.monto_exento
                total += d.monto_total
            for d in r.detalles:
                if d.tpo_doc.sii_code in [39, 41] and d.tipo_operacion == "utilizados":
                    total_boletas += d.cantidad
            r.total_neto = total - total_iva - total_exento
            r.total_iva = total_iva
            r.total_exento = total_exento
            r.total = total
            r.total_boletas = total_boletas


    @api.onchange('move_ids', 'anulaciones')
    def _resumenes(self):
        resumenes, TpoDocs = self._get_resumenes()
        if self.impuestos and isinstance(self.id, int):
            self._cr.execute("DELETE FROM account_move_consumo_folios_impuestos WHERE cf_id=%s", (self.id,))
            self.invalidate_cache()
        if self.detalles and isinstance(self.id, int):
            self._cr.execute("DELETE FROM account_move_consumo_folios_detalles WHERE cf_id=%s", (self.id,))
            self.invalidate_cache()
        detalles = [[5,],]
        def pushItem(key_item, item, tpo_doc):
            rango = {
                'tipo_operacion': 'utilizados' if key_item == 'RangoUtilizados' else 'anulados',
                'folio_inicio': item['Inicial'],
                'folio_final': item['Final'],
                'cantidad': int(item['Final']) - int(item['Inicial']) +1,
                'tpo_doc': self.env['sii.document_class'].search([('sii_code', '=', tpo_doc)]).id,
            }
            detalles.append([0,0,rango])
        for r, value in resumenes.items():
            if '%s_folios' %str(r) in value:
                Rangos = value[ str(r)+'_folios' ]
                if 'itemUtilizados' in Rangos:
                    for rango in Rangos['itemUtilizados']:
                        pushItem('RangoUtilizados', rango, r)
                if 'itemAnulados' in Rangos:
                    for rango in Rangos['itemAnulados']:
                        pushItem('RangoAnulados', rango, r)
        self.detalles = detalles
        docs = collections.OrderedDict()
        for r, value in resumenes.items():
            if value.get('FoliosUtilizados', False):
                docs[r] = {
                       'tpo_doc': self.env['sii.document_class'].search([('sii_code','=', r)]).id,
                       'cantidad': value['FoliosUtilizados'],
                       'monto_neto': value['MntNeto'],
                       'monto_iva': value['MntIva'],
                       'monto_exento': value['MntExento'],
                       'monto_total': value['MntTotal'],
                       }
        lines = [[5,],]
        for key, i in docs.items():
            i['currency_id'] = self.env.user.company_id.currency_id.id
            lines.append([0,0, i])
        self.impuestos = lines

    @api.onchange('fecha_inicio', 'company_id', 'fecha_final')
    def set_data(self):
        current = datetime.now().strftime('%Y-%m-%d') + ' 00:00:00'
        tz = pytz.timezone('America/Santiago')
        tz_current = tz.localize(datetime.strptime(current, DTF)).astimezone(pytz.utc)
        current = tz_current.strftime(DTF)
        fi = datetime.strptime(self.fecha_inicio + " 00:00:00", DTF)
        if fi > datetime.strptime(current, DTF):
            raise UserError("No puede hacer Consumo de Folios de días futuros")
        self.name = self.fecha_inicio
        self.fecha_final = self.fecha_inicio
        self.move_ids = self.env['account.move'].search([
            ('document_class_id.sii_code', 'in', [39, 41]),
#            ('sended','=', False),
            ('date', '=', self.fecha_inicio),
            ('company_id', '=', self.company_id.id),
            ]).ids
        consumos = self.search_count([
            ('fecha_inicio', '=', self.fecha_inicio),
            ('state', 'not in', ['draft', 'Rechazado']),
            ('company_id', '=', self.company_id.id),
            ])
        if consumos > 0:
            self.sec_envio = (consumos+1)
        self._resumenes()

    @api.multi
    def copy(self, default=None):
        res = super(ConsumoFolios, self).copy(default)
        res.set_data()
        return res

    @api.multi
    def unlink(self):
        for cf in self:
            if cf.state not in ('draft', 'cancel'):
                raise UserError(_('You cannot delete a Validated Consumo de Folios.'))
        return super(ConsumoFolios, self).unlink()

    def create_template_envio(self, RutEmisor, FchResol, NroResol, FchInicio,\
                               FchFinal, Correlativo, SecEnvio, EnvioDTE,\
                               subject_serial_number, IdEnvio='SetDoc'):
        if Correlativo != 0:
            Correlativo = "<Correlativo>"+str(Correlativo)+"</Correlativo>"
        else:
            Correlativo = ''
        xml = '''<DocumentoConsumoFolios ID="{10}">
<Caratula  version="1.0" >
<RutEmisor>{0}</RutEmisor>
<RutEnvia>{1}</RutEnvia>
<FchResol>{2}</FchResol>
<NroResol>{3}</NroResol>
<FchInicio>{4}</FchInicio>
<FchFinal>{5}</FchFinal>{6}
<SecEnvio>{7}</SecEnvio>
<TmstFirmaEnv>{8}</TmstFirmaEnv>
</Caratula>
{9}
</DocumentoConsumoFolios>
'''.format(RutEmisor, subject_serial_number,
           FchResol, NroResol, FchInicio, FchFinal, str(Correlativo), str(SecEnvio), self.time_stamp(), EnvioDTE,  IdEnvio)
        return xml

    def time_stamp(self, formato='%Y-%m-%dT%H:%M:%S'):
        tz = pytz.timezone('America/Santiago')
        return datetime.now(tz).strftime(formato)

    def create_template_env(self, doc,simplificado=False):
        xsd = 'http://www.sii.cl/SiiDte ConsumoFolio_v10.xsd'
        xml = '''<ConsumoFolios xmlns="http://www.sii.cl/SiiDte" \
xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" \
xsi:schemaLocation="{0}" \
version="1.0">
{1}</ConsumoFolios>'''.format(xsd, doc)
        return xml

    def get_resolution_data(self, comp_id):
        resolution_data = {
            'dte_resolution_date': comp_id.dte_resolution_date,
            'dte_resolution_number': comp_id.dte_resolution_number}
        return resolution_data

    @api.multi
    def get_xml_file(self):
        return {
            'type' : 'ir.actions.act_url',
            'url': '/download/xml/cf/%s' % (self.id),
            'target': 'self',
        }

    def format_vat(self, value):
        ''' Se Elimina el 0 para prevenir problemas con el sii, ya que las muestras no las toma si va con
        el 0 , y tambien internamente se generan problemas'''
        if not value or value=='' or value == 0:
            value ="CL666666666"
            #@TODO opción de crear código de cliente en vez de rut genérico
        rut = value[:10] + '-' + value[10:]
        rut = rut.replace('CL0','').replace('CL','')
        return rut

    @api.multi
    def validar_consumo_folios(self):
        self._validar()
        consumos = self.search([
            ('fecha_inicio', '=', self.fecha_inicio),
            ('state', 'not in', ['draft', 'Rechazado', 'Anulado']),
            ('company_id', '=', self.company_id.id),
            ('id', '!=', self.id),
            ])
        for r in consumos:
            r.state = "Anulado"
        return self.write({'state': 'NoEnviado'})

    def _acortar_str(self, texto, size=1):
        c = 0
        cadena = ""
        while c < size and c < len(texto):
            cadena += texto[c]
            c += 1
        return cadena

    def _es_iva(self, tax):
        if tax.sii_code in [14, 15, 17, 18, 19, 30,31, 32 ,33, 34, 36, 37, 38, 39, 41, 47, 48]:
            return True
        return False

    def _get_totales(self, rec):
        Neto = 0
        MntExe = 0
        TaxMnt = 0
        MntTotal = 0
        for l in rec.line_ids:
            if l.tax_line_id:
                if l.tax_line_id and l.tax_line_id.amount > 0: #supuesto iva único
                    if self._es_iva(l.tax_line_id): # diferentes tipos de IVA retenidos o no
                        if l.credit > 0:
                            TaxMnt += l.credit
                        else:
                            TaxMnt += l.debit
            elif l.tax_ids and l.tax_ids[0].amount > 0:
                if l.credit > 0:
                    Neto += l.credit
                else:
                    Neto += l.debit
            elif l.tax_ids and l.tax_ids[0].amount == 0: #caso monto exento
                if l.credit > 0:
                    MntExe += l.credit
                else:
                    MntExe += l.debit
        MntTotal = Neto + MntExe + TaxMnt
        TasaIVA = self.env['account.move.line'].search([
                ('move_id', '=', rec.id), 
                ('tax_line_id.amount', '>', 0)
            ], limit=1).tax_line_id.amount
        return Neto, MntExe, TaxMnt, MntTotal, TasaIVA

    def getResumen(self, rec):
        det = collections.OrderedDict()
        det['TpoDoc'] = rec.document_class_id.sii_code
        det['NroDoc'] = int(rec.sii_document_number)
        for a in self.anulaciones:
            if a.rango_inicio <= det['NroDoc'] and det['NroDoc'] <= a.rango_final and a.tpo_doc.id == rec.document_class_id.id:
                rec.canceled = True
        if rec.canceled:
            det['Anulado'] = 'A'
            return det
        Neto, MntExe, TaxMnt, MntTotal, TasaIVA = self._get_totales(rec)
        if MntExe > 0 :
            det['MntExe'] = self.currency_id.round(MntExe)
        if TaxMnt > 0:
            det['MntIVA'] = self.currency_id.round(TaxMnt)
            det['TasaIVA'] = TasaIVA
        det['MntNeto'] = self.currency_id.round(Neto)
        det['MntTotal'] = self.currency_id.round(MntTotal)
        return det

    def _last(self, folio, items):# se asumen que vienen ordenados de menor a mayor
        last = False
        for c in items:
            if folio > c['Final'] and folio > c['Inicial']:
                if not last or last['Inicial'] < c['Inicial']:
                    last = c
        return last

    def _nuevo_rango(self, folio, f_contrario, contrarios):
        last = self._last(folio, contrarios)#obtengo el último tramo de los contrarios
        if last and last['Inicial'] > f_contrario:
            return True
        return False

    def _orden(self, folio, rangos, contrarios, continuado=True):
        last = self._last(folio, rangos)
        if not continuado or not last or  self._nuevo_rango(folio, last['Final'], contrarios):
            r = collections.OrderedDict()
            r['Inicial'] = folio
            r['Final'] = folio
            rangos.append(r)
            return rangos
        result = []
        for r in rangos:
            if r['Final'] == last['Final'] and folio > last['Final']:
                r['Final'] = folio
            result.append(r)
        return result

    def _rangosU(self, resumen, rangos, continuado=True):
        if not rangos:
            rangos = collections.OrderedDict()
        folio = resumen['NroDoc']
        if 'Anulado' in resumen and resumen['Anulado']:
            utilizados = rangos['itemUtilizados'] if 'itemUtilizados' in rangos else []
            if not 'itemAnulados' in rangos:
                rangos['itemAnulados'] = []
                r = collections.OrderedDict()
                r['Inicial'] = folio
                r['Final'] = folio
                rangos['itemAnulados'].append(r)
            else:
                rangos['itemAnulados'] = self._orden(resumen['NroDoc'], rangos['itemAnulados'], utilizados, continuado)
            return rangos
        anulados = rangos['itemAnulados'] if 'itemAnulados' in rangos else []
        if not 'itemUtilizados' in rangos:
            rangos['itemUtilizados'] = []
            r = collections.OrderedDict()
            r['Inicial'] = folio
            r['Final'] = folio
            rangos['itemUtilizados'].append(r)
        else:
            rangos['itemUtilizados'] = self._orden(resumen['NroDoc'], rangos['itemUtilizados'], anulados, continuado)
        return rangos

    def _setResumen(self,resumen,resumenP,continuado=True):
        resumenP['TipoDocumento'] = resumen['TpoDoc']
        if not 'Anulado' in resumen:
            if 'MntNeto' in resumen and not 'MntNeto' in resumenP:
                resumenP['MntNeto'] = resumen['MntNeto']
            elif 'MntNeto' in resumen:
                resumenP['MntNeto'] += resumen['MntNeto']
            elif not 'MntNeto' in resumenP:
                resumenP['MntNeto'] = 0
            if 'MntIVA' in resumen and not 'MntIva' in resumenP:
                resumenP['MntIva'] = resumen['MntIVA']
            elif 'MntIVA' in resumen:
                resumenP['MntIva'] += resumen['MntIVA']
            elif not 'MntIva' in resumenP:
                resumenP['MntIva'] = 0
            if 'TasaIVA' in resumen and not 'TasaIVA' in resumenP:
                resumenP['TasaIVA'] = resumen['TasaIVA']
            if 'MntExe' in resumen and not 'MntExento' in resumenP:
                resumenP['MntExento'] = resumen['MntExe']
            elif 'MntExe' in resumen:
                resumenP['MntExento'] += resumen['MntExe']
            elif not 'MntExento' in resumenP:
                resumenP['MntExento'] = 0
        if not 'MntTotal' in resumenP:
            resumenP['MntTotal'] = resumen.get('MntTotal', 0)
        else:
            resumenP['MntTotal'] += resumen.get('MntTotal', 0)
        if 'FoliosEmitidos' in resumenP:
            resumenP['FoliosEmitidos'] +=1
        else:
            resumenP['FoliosEmitidos'] = 1

        if not 'FoliosAnulados' in resumenP:
            resumenP['FoliosAnulados'] = 0
        if 'Anulado' in resumen : # opción de indiar de que está anulado por panel SII no por nota
            resumenP['FoliosAnulados'] += 1
        elif 'FoliosUtilizados' in resumenP:
            resumenP['FoliosUtilizados'] += 1
        else:
            resumenP['FoliosUtilizados'] = 1
        if not resumenP.get('FoliosUtilizados', False):
            resumenP['FoliosUtilizados'] = 0
        if not str(resumen['TpoDoc'])+'_folios' in resumenP:
            resumenP[str(resumen['TpoDoc'])+'_folios'] = collections.OrderedDict()
        resumenP[str(resumen['TpoDoc'])+'_folios'] = self._rangosU(resumen, resumenP[str(resumen['TpoDoc'])+'_folios'], continuado)
        return resumenP

    def _get_moves(self):
        recs = []
        for rec in self.with_context(lang='es_CL').move_ids:
            document_class_id = rec.document_class_id
            if not document_class_id or document_class_id.sii_code not in [39, 41, 61]:
                _logger.warning("Por este medio solamente se pueden declarar Boletas o Notas de crédito Electrónicas, por favor elimine el documento %s del listado" % rec.name)
                continue
            if rec.sii_document_number:
                recs.append(rec)
        return recs

    def _get_resumenes(self, marc=False):
        resumenes = collections.OrderedDict()
        TpoDocs = []
        recs = self._get_moves()
        if recs:
            recs = sorted(recs, key=lambda t: int(t.sii_document_number))
            ant = {}
            for order in recs:
                canceled = (hasattr(order, 'canceled') and order.canceled)
                resumen = self.getResumen(order)
                TpoDoc = str(resumen['TpoDoc'])
                if TpoDoc not in ant:
                    ant[TpoDoc] = [0, canceled]
                if int(order.sii_document_number) == ant[TpoDoc][0]:
                    raise UserError("¡El Folio %s está duplicado!" % order.sii_document_number)
                if TpoDoc not in TpoDocs:
                    TpoDocs.append(TpoDoc)
                if TpoDoc not in resumenes:
                    resumenes[TpoDoc] = collections.OrderedDict()
                continuado = ((ant[TpoDoc][0]+1) == int(order.sii_document_number) and (ant[TpoDoc][1]) == canceled)
                resumenes[TpoDoc] = self._setResumen(resumen, resumenes[TpoDoc], continuado)
                ant[TpoDoc] = [int(order.sii_document_number), canceled]
        for an in self.anulaciones:
            TpoDoc = str(an.tpo_doc.sii_code)
            if TpoDoc not in TpoDocs:
                TpoDocs.append(TpoDoc)
            if TpoDoc not in resumenes:
                resumenes[TpoDoc] = collections.OrderedDict()
            i = an.rango_inicio
            while i <= an.rango_final:
                continuado  = False
                seted = False
                for r, value in resumenes.items():
                    Rangos = value.get(str(r)+'_folios', collections.OrderedDict())
                    if 'itemAnulados' in Rangos:
                        for rango in Rangos['itemAnulados']:
                            if rango['Inicial'] <= i and i <= rango['Final']:
                                seted = True
                            if not(seted) and (i-1) == rango['Final']:
                                    continuado = True
                if not seted:
                    resumen = {
                        'TpoDoc': TpoDoc,
                        'NroDoc': i,
                        'Anulado': 'A',
                    }
                    if not resumenes.get(TpoDoc):
                        resumenes[TpoDoc] = collections.OrderedDict()
                    resumenes[TpoDoc] = self._setResumen(resumen, resumenes[TpoDoc], continuado)
                i += 1
        return resumenes, TpoDocs

    def _validar(self):
        cant_doc_batch = 0
        company_id = self.company_id
        dte_service = company_id.dte_service_provider
        signature_id = self.env.user.get_digital_signature(self.company_id)
        if not signature_id:
            raise UserError(_('''There is no Signer Person with an \
        authorized signature for you in the system. Please make sure that \
        'user_signature_key' module has been installed and enable a digital \
        signature, for you or make the signer to authorize you to use his \
        signature.'''))
        resumenes, TpoDocs = self._get_resumenes(marc=True)
        Resumen = []
        listado = [ 'TipoDocumento', 'MntNeto', 'MntIva', 'TasaIVA', 'MntExento', 'MntTotal', 'FoliosEmitidos',  'FoliosAnulados', 'FoliosUtilizados', 'itemUtilizados' ]
        xml = '<Resumen><TipoDocumento>39</TipoDocumento><MntTotal>0</MntTotal><FoliosEmitidos>0</FoliosEmitidos><FoliosAnulados>0</FoliosAnulados><FoliosUtilizados>0</FoliosUtilizados></Resumen>'
        if resumenes:
            for r, value in resumenes.items():
                ordered = collections.OrderedDict()
                for i in listado:
                    if i in value:
                        ordered[i] = value[i]
                    elif i == 'itemUtilizados':
                        Rangos = value[ str(r)+'_folios' ]
                        folios = []
                        if 'itemUtilizados' in Rangos:
                            utilizados = []
                            for rango in Rangos['itemUtilizados']:
                                utilizados.append({'RangoUtilizados': rango})
                            folios.append({'itemUtilizados': utilizados})
                        if 'itemAnulados' in Rangos:
                            anulados = []
                            for rango in Rangos['itemAnulados']:
                                anulados.append({'RangoAnulados': rango})
                            folios.append({'itemAnulados': anulados})
                        ordered[ str(r)+'_folios' ] = folios
                Resumen.extend([ {'Resumen': ordered}])
            dte = collections.OrderedDict({'item':Resumen})
            xml = dicttoxml.dicttoxml(
                dte,
                root=False,
                attr_type=False).decode()
        resol_data = self.get_resolution_data(company_id)
        RUTEmisor = self.format_vat(company_id.vat)
        RUTRecep = "60803000-K" # RUT SII
        doc_id =  'CF_'+self.date
        Correlativo = self.correlativo
        SecEnvio = self.sec_envio
        cf = self.create_template_envio( RUTEmisor,
            resol_data['dte_resolution_date'],
            resol_data['dte_resolution_number'],
            self.fecha_inicio,
            self.fecha_final,
            Correlativo,
            SecEnvio,
            xml,
            signature_id.subject_serial_number,
            doc_id)
        xml  = self.create_template_env(cf)
        root = etree.XML( xml )
        xml_pret = etree.tostring(root, pretty_print=True).decode()\
                .replace('<item>','\n').replace('</item>','')\
                .replace('<itemNoRec>','').replace('</itemNoRec>','\n')\
                .replace('<itemOtrosImp>','').replace('</itemOtrosImp>','\n')\
                .replace('<itemUtilizados>','').replace('</itemUtilizados>','\n')\
                .replace('<itemAnulados>','').replace('</itemAnulados>','\n')
        for TpoDoc in TpoDocs:
        	xml_pret = xml_pret.replace('<key name="'+str(TpoDoc)+'_folios">','').replace('</key>','\n').replace('<key name="'+str(TpoDoc)+'_folios"/>','\n')
        envio_dte = self.env['account.invoice'].sign_full_xml(
            xml_pret,
            doc_id,
            'consu')
        doc_id += '.xml'
        self.sii_xml_request = self.env['sii.xml.envio'].create({
            'xml_envio': '<?xml version="1.0" encoding="ISO-8859-1"?>\n%s' % envio_dte,
            'name': doc_id,
            'company_id': self.company_id.id,
            'state': 'draft',
        }).id

    @api.multi
    def do_dte_send_consumo_folios(self):
        if self.state not in ['draft', 'NoEnviado', 'Rechazado']:
            raise UserError("El Consumo de Folios ya ha sido enviado")
        if not self.sii_xml_request or self.sii_xml_request.state == "Rechazado":
            if self.sii_xml_request:
                self.sii_xml_request.unlink()
            self._validar()
        self.env['sii.cola_envio'].create(
                    {
                        'doc_ids': [self.id],
                        'model': 'account.move.consumo_folios',
                        'user_id': self.env.user.id,
                        'tipo_trabajo': 'envio',
                    })
        self.state = 'EnCola'

    def do_dte_send(self, n_atencion=''):
        if self.sii_xml_request and self.sii_xml_request.state == "Rechazado":
            self.sii_xml_request.unlink()
            self._validar()
            self.sii_xml_request.state = 'NoEnviado'
        self.sii_xml_request.send_xml()
        return self.sii_xml_request

    def _get_send_status(self):
        self.sii_xml_request.get_send_status()
        if self.sii_xml_request.state == 'Aceptado':
            self.state = "Proceso"
        else:
            self.state = self.sii_xml_request.state

    @api.multi
    def ask_for_dte_status(self):
        self._get_send_status()

    def get_sii_result(self):
        for r in self:
            if r.sii_xml_request.state == 'NoEnviado':
                r.state = 'EnCola'
                continue
            r.state = r.sii_xml_request.state


class DetalleCOnsumoFolios(models.Model):
    _name = "account.move.consumo_folios.detalles"

    cf_id = fields.Many2one('account.move.consumo_folios',
                            string="Consumo de Folios")
    tpo_doc = fields.Many2one('sii.document_class',
                              string="Tipo de Documento")
    tipo_operacion = fields.Selection([('utilizados','Utilizados'), ('anulados','Anulados')])
    folio_inicio = fields.Integer(string="Folio Inicio")
    folio_final = fields.Integer(string="Folio Final")
    cantidad = fields.Integer(string="Cantidad Emitidos")


class DetalleImpuestos(models.Model):
    _name = "account.move.consumo_folios.impuestos"

    cf_id = fields.Many2one('account.move.consumo_folios',
                            string="Consumo de Folios")
    tpo_doc = fields.Many2one('sii.document_class',
                              string="Tipo de Documento")
    impuesto = fields.Many2one('account.tax')
    cantidad = fields.Integer(string="Cantidad")
    monto_neto = fields.Monetary(string="Monto Neto")
    monto_iva = fields.Monetary(string="Monto IVA",)
    monto_exento = fields.Monetary(string="Monto Exento",)
    monto_total = fields.Monetary(string="Monto Total",)
    currency_id = fields.Many2one('res.currency',
        string='Moneda',
        default=lambda self: self.env.user.company_id.currency_id,
        required=True,
        track_visibility='always')


class Anulaciones(models.Model):
    _name = 'account.move.consumo_folios.anulaciones'

    cf_id = fields.Many2one(
            'account.move.consumo_folios',
            string="Consumo de Folios",
        )
    tpo_doc = fields.Many2one(
            'sii.document_class',
            string="Tipo de documento",
            required=True,
            domain=[('sii_code','in',[ 39 , 41, 61])],
        )
    rango_inicio = fields.Integer(
        required=True,
        string="Rango Inicio")
    rango_final = fields.Integer(
        required=True,
        string="Rango Final")
