# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.tools.translate import _
from odoo.exceptions import UserError
import logging
import base64
import xmltodict
from lxml import etree
import collections
import dicttoxml

_logger = logging.getLogger(__name__)


class UploadXMLWizard(models.TransientModel):
    _name = 'sii.dte.upload_xml.wizard'
    _description = 'SII XML from Provider'

    action = fields.Selection(
        [
            ('create_po', 'Crear Orden de Pedido y Factura'),
            ('create', 'Crear Solamente Factura'),
        ],
        string="Acción",
        default="create",
    )
    xml_file = fields.Binary(
        string='XML File',
        filters='*.xml',
        store=True,
        help='Upload the XML File in this holder',
    )
    filename = fields.Char(
        string='File Name',
    )
    pre_process = fields.Boolean(
        default=True,
    )
    dte_id = fields.Many2one(
        'mail.message.dte',
        string="DTE",
    )
    document_id = fields.Many2one(
        'mail.message.dte.document',
        string="Documento",
    )
    option = fields.Selection(
        [
            ('upload', 'Solo Subir'),
            ('accept', 'Aceptar'),
            ('reject', 'Rechazar'),
        ],
        string="Opción",
    )
    num_dtes = fields.Integer(
        string="Número de DTES",
        readonly=True,
    )
    type = fields.Selection(
        [
            ('ventas', 'Ventas'),
            ('compras', 'Compras'),
        ],
        string="Tipo de Operación",
        default='compras',
    )

    @api.onchange('xml_file')
    def get_num_dtes(self):
        if self.xml_file:
            self.num_dtes = len(self._get_dtes())

    @api.multi
    def confirm(self, ret=False):
        context = dict(self._context or {})
        active_id = context.get('active_id', []) or []
        created = []
        if not self.dte_id:
            dte_id = self.env['mail.message.dte'].search(
                [
                    ('name', '=', self.filename),
                ]
            )
            if not dte_id:
                dte = {
                    'name': self.filename,
                }
                dte_id = self.env['mail.message.dte'].create(dte)
            self.dte_id = dte_id
        if self.type == 'ventas':
            created = self.do_create_inv()
            xml_id = 'account.action_invoice_tree2'
            target_model = 'account.invoice'
        elif self.pre_process or self.action == 'upload':
            created = self.do_create_pre()
            xml_id = 'l10n_cl_fe.action_dte_process'
            target_model = 'mail.message.dte'
        elif self.option == 'reject':
            self.do_reject()
            return
        elif self.action == 'create':
            created = self.do_create_inv()
            xml_id = 'account.action_invoice_tree2'
            target_model = 'account.invoice'
        if self.action == 'create_po':
            self.do_create_po()
            xml_id = 'purchase.purchase_order_tree'
            target_model = 'purchase.order'
        if ret:
            return created
        return {
            'type': 'ir.actions.act_window',
            'name': _('List of Results'),
            'view_type': 'form',
            'view_mode': 'tree',
            'res_model': target_model,
            'domain': str([('id', 'in', created)]),
            'views': [(self.env.ref('%s' % (xml_id)).id, 'tree')],
        }

    def format_rut(self, RUTEmisor=None):
        rut = RUTEmisor.replace('-', '')
        if int(rut[:-1]) < 10000000:
            rut = '0' + str(rut)
        rut = 'CL' + rut
        return rut

    def _read_xml(self, mode="text", check=False):
        if self.document_id:
            xml = self.document_id.xml
        elif self.xml_file:
            xml = base64.b64decode(self.xml_file).decode('ISO-8859-1').replace('<?xml version="1.0" encoding="ISO-8859-1"?>','').replace('<?xml version="1.0" encoding="ISO-8859-1" ?>','')
            if check:
                return xml
            xml = xml.replace(' xmlns="http://www.sii.cl/SiiDte"', '')
        if mode == "etree":
            parser = etree.XMLParser(remove_blank_text=True)
            return etree.fromstring(xml, parser=parser)
        if mode == "parse":
            envio = xmltodict.parse(xml)
            if 'EnvioBOLETA' in envio:
                return envio['EnvioBOLETA']
            elif 'EnvioDTE' in envio:
                return envio['EnvioDTE']
            else:
                return envio
        return xml

    def _check_digest_caratula(self):
        xml = etree.fromstring(self._read_xml(False))
        string = etree.tostring(xml[0])
        mess = etree.tostring(etree.fromstring(string), method="c14n")
        inv_obj = self.env['account.invoice']
        #our = base64.b64encode(inv_obj.digest(mess))
        #if our != xml.find("{http://www.w3.org/2000/09/xmldsig#}Signature/{http://www.w3.org/2000/09/xmldsig#}SignedInfo/{http://www.w3.org/2000/09/xmldsig#}Reference/{http://www.w3.org/2000/09/xmldsig#}DigestValue").text:
        #    return 2, 'Envio Rechazado - Error de Firma'
        return 0, 'Envio Ok'

    def _check_digest_dte(self, dte):
        xml = self._read_xml("etree")
        envio = xml.find("SetDTE")#"{http://www.w3.org/2000/09/xmldsig#}Signature/{http://www.w3.org/2000/09/xmldsig#}SignedInfo/{http://www.w3.org/2000/09/xmldsig#}Reference/{http://www.w3.org/2000/09/xmldsig#}DigestValue").text
        for e in envio.findall("DTE"):
            string = etree.tostring(e.find("Documento"))#doc
            mess = etree.tostring(etree.fromstring(string), method="c14n").decode('iso-8859-1').replace(' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"','').encode('iso-8859-1')# el replace es necesario debido a que python lo agrega solo
            #our = base64.b64encode(self.env['account.invoice'].digest(mess))
            #their = e.find("{http://www.w3.org/2000/09/xmldsig#}Signature/{http://www.w3.org/2000/09/xmldsig#}SignedInfo/{http://www.w3.org/2000/09/xmldsig#}Reference/{http://www.w3.org/2000/09/xmldsig#}DigestValue").text
            #if our != their:
            #    _logger.warning('DTE No Recibido - Error de Firma: our = %s their=%s' % (our, their))
                #return 1, 'DTE No Recibido - Error de Firma'
        return 0, 'DTE Recibido OK'

    def _validar_caratula(self, cara):
        try:
            self.env['account.invoice'].xml_validator(
                self._read_xml(False, check=True).encode(),
                'env',
            )
        except:
               return 1, 'Envio Rechazado - Error de Schema'
        self.dte_id.company_id = self.env['res.company'].search([
                ('vat','=', self.format_rut(cara['RutReceptor']))
            ])
        if not self.dte_id.company_id:
            return 3, 'Rut no corresponde a nuestra empresa'
        partner_id = self.env['res.partner'].search(
            [
                ('active', '=', True),
                ('parent_id', '=', False),
                ('vat', '=', self.format_rut(cara['RutEmisor']))
            ]
        )
#        if not partner_id :
#            return 2, 'Rut no coincide con los registros'
        #for SubTotDTE in cara['SubTotDTE']:
        #    sii_document_class = self.env['sii.document_class'].search([('sii_code','=', str(SubTotDTE['TipoDTE']))])
        #    if not sii_document_class:
        #        return  99, 'Tipo de documento desconocido'
        return 0, 'Envío Ok'

    def _validar(self, doc):
        cara, glosa = self._validar_caratula(doc[0][0]['Caratula'])
        return cara, glosa

    def _validar_dte(self, doc):
        res = collections.OrderedDict()
        res['TipoDTE'] = doc['Encabezado']['IdDoc']['TipoDTE']
        res['Folio'] = doc['Encabezado']['IdDoc']['Folio']
        res['FchEmis'] = doc['Encabezado']['IdDoc']['FchEmis']
        res['RUTEmisor'] = doc['Encabezado']['Emisor']['RUTEmisor']
        res['RUTRecep'] = doc['Encabezado']['Receptor']['RUTRecep']
        res['MntTotal'] = doc['Encabezado']['Totales']['MntTotal']
        partner_id = self.env['res.partner'].search([
            ('active', '=', True),
            ('parent_id', '=', False),
            ('vat', '=', self.format_rut(doc['Encabezado']['Emisor']['RUTEmisor']))
        ])
        sii_document_class = doc['Encabezado']['IdDoc']['TipoDTE']
        res['EstadoRecepDTE'] = 0
        res['RecepDTEGlosa'] = 'DTE Recibido OK'
        res['EstadoRecepDTE'], res['RecepDTEGlosa'] = self._check_digest_dte(doc)
        if not sii_document_class:
            res['EstadoRecepDTE'] = 99
            res['RecepDTEGlosa'] = 'Tipo de documento desconocido'
            return res
        docu = self.env['account.invoice'].search(
            [
                ('reference', '=', doc['Encabezado']['IdDoc']['Folio']),
                ('partner_id', '=', partner_id.id),
                ('document_class_id.sii_code', '=', sii_document_class)
            ])
        company_id = self.env['res.company'].search([
                ('vat', '=', self.format_rut(doc['Encabezado']['Receptor']['RUTRecep']))
            ])
        if not company_id and (not docu or doc['Encabezado']['Receptor']['RUTRecep'] != self.env['account.invoice'].format_vat(docu.company_id.vat) ) :
            res['EstadoRecepDTE'] = 3
            res['RecepDTEGlosa'] = 'Rut no corresponde a la empresa esperada'
            return res
        return res

    def _validar_dtes(self):
        envio = self._read_xml('parse')
        if 'Documento' in envio['SetDTE']['DTE']:
            res = {'RecepcionDTE': self._validar_dte(envio['SetDTE']['DTE']['Documento'])}
        else:
            res = []
            for doc in envio['SetDTE']['DTE']:
                res.extend([
                    {'RecepcionDTE': self._validar_dte(doc['Documento'])}
                    ])
        return res

    def _caratula_respuesta(self, RutResponde, RutRecibe, IdRespuesta="1", NroDetalles=0):
        caratula = collections.OrderedDict()
        caratula['RutResponde'] = RutResponde
        caratula['RutRecibe'] = RutRecibe
        caratula['IdRespuesta'] = IdRespuesta
        caratula['NroDetalles'] = NroDetalles
        caratula['NmbContacto'] = self.env.user.partner_id.name
        caratula['FonoContacto'] = self.env.user.partner_id.phone
        caratula['MailContacto'] = self.env.user.partner_id.email
        caratula['TmstFirmaResp'] = self.env['account.invoice'].time_stamp()
        return caratula

    def _receipt(self, IdRespuesta):
        envio = self._read_xml('parse')
        xml = self._read_xml('etree')
        resp = collections.OrderedDict()
        inv_obj = self.env['account.invoice']
        resp['NmbEnvio'] = self.filename
        resp['FchRecep'] = inv_obj.time_stamp()
        resp['CodEnvio'] = inv_obj._acortar_str(IdRespuesta, 10)
        resp['EnvioDTEID'] = xml[0].attrib['ID']
        resp['Digest'] = xml.find("{http://www.w3.org/2000/09/xmldsig#}Signature/{http://www.w3.org/2000/09/xmldsig#}SignedInfo/{http://www.w3.org/2000/09/xmldsig#}Reference/{http://www.w3.org/2000/09/xmldsig#}DigestValue").text
        EstadoRecepEnv, RecepEnvGlosa = self._validar_caratula(envio['SetDTE']['Caratula'])
        if EstadoRecepEnv == 0:
            EstadoRecepEnv, RecepEnvGlosa = self._check_digest_caratula()
        resp['RutEmisor'] = envio['SetDTE']['Caratula']['RutEmisor']
        resp['RutReceptor'] = envio['SetDTE']['Caratula']['RutReceptor']
        resp['EstadoRecepEnv'] = EstadoRecepEnv
        resp['RecepEnvGlosa'] = RecepEnvGlosa
        NroDte = len(envio['SetDTE']['DTE'])
        if 'Documento' in envio['SetDTE']['DTE']:
            NroDte = 1
        resp['NroDTE'] = NroDte
        resp['item'] = self._validar_dtes()
        return resp

    def _RecepcionEnvio(self, Caratula, resultado):
        resp = '''<?xml version="1.0" encoding="ISO-8859-1"?>
<RespuestaDTE version="1.0" xmlns="http://www.sii.cl/SiiDte" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.sii.cl/SiiDte RespuestaEnvioDTE_v10.xsd" >
    <Resultado ID="Odoo_resp">
        <Caratula version="1.0">
            {0}
        </Caratula>
            {1}
    </Resultado>
</RespuestaDTE>'''.format(Caratula, resultado)
        return resp

    def _create_attachment(self, xml, name, id=False, model='account.invoice'):
        data = base64.b64encode(xml.encode('ISO-8859-1'))
        filename = (name + '.xml').replace(' ', '')
        url_path = '/download/xml/resp/%s' % (id)
        att = self.env['ir.attachment'].search(
            [
                ('name', '=', filename),
                ('res_id', '=', id),
                ('res_model', '=', model)
            ],
            limit=1)
        if att:
            return att
        values = dict(
                        name=filename,
                        datas_fname=filename,
                        url=url_path,
                        res_model=model,
                        res_id=id,
                        type='binary',
                        datas=data,
                    )
        att = self.env['ir.attachment'].create(values)
        return att

    def do_receipt_deliver(self):
        envio = self._read_xml('parse')
        if not envio.get('SetDTE') or not envio['SetDTE'].get('Caratula'):
            return True
        company_id = self.env['res.company'].search(
            [
                ('vat', '=', self.format_rut(envio['SetDTE']['Caratula']['RutReceptor']))
            ],
            limit=1)
        IdRespuesta = self.env.ref('l10n_cl_fe.response_sequence').next_by_id()
        recep = self._receipt(IdRespuesta)
        NroDetalles = len(envio['SetDTE']['DTE'])
        resp_dtes = dicttoxml.dicttoxml(recep, root=False, attr_type=False).decode().replace('<item>','\n').replace('</item>','\n')
        RecepcionEnvio = '''
<RecepcionEnvio>
    {0}
</RecepcionEnvio>
        '''.format(
            resp_dtes,
        )
        RutRecibe = envio['SetDTE']['Caratula']['RutEmisor']
        caratula_recepcion_envio = self._caratula_respuesta(
            self.env['account.invoice'].format_vat(company_id.vat),
            RutRecibe,
            IdRespuesta,
            NroDetalles,
        )
        caratula = dicttoxml.dicttoxml(
            caratula_recepcion_envio,
            root=False,
            attr_type=False,
        ).decode().replace('<item>', '\n').replace('</item>', '\n')
        resp = self._RecepcionEnvio(caratula, RecepcionEnvio )
        respuesta = '<?xml version="1.0" encoding="ISO-8859-1"?>\n'+self.env['account.invoice'].sudo().with_context({'company_id': company_id.id}).sign_full_xml(
            resp.replace('<?xml version="1.0" encoding="ISO-8859-1"?>\n', ''),
            'Odoo_resp',
            'env_resp')
        if self.dte_id:
            att = self._create_attachment(
                respuesta,
                'recepcion_envio_' + (self.filename or self.dte_id.name) + '_' + str(IdRespuesta),
                self.dte_id.id,
                'mail.message.dte')
            dte_email_id = self.dte_id.company_id.dte_email_id or self.env.user.company_id.dte_email_id
            values = {
                    'res_id': self.dte_id.id,
                    'email_from': dte_email_id.name_get()[0][1],
                    'email_to': self.sudo().dte_id.mail_id.email_from,
                    'auto_delete': False,
                    'model': "mail.message.dte",
                    'body': 'XML de Respuesta Envío, Estado: %s , Glosa: %s ' % (recep['EstadoRecepEnv'], recep['RecepEnvGlosa'] ),
                    'subject': 'XML de Respuesta Envío',
                    'attachment_ids': [[6, 0, att.ids]],
                }
            send_mail = self.env['mail.mail'].sudo().create(values)
            send_mail.send()

    def _create_partner(self, data):
        if self.pre_process and self.type == 'compras':
            return False
        type = "Emis"
        if self.type == 'ventas':
            type = "Recep"
            if data.get('RUT%s' % type) in [False, '66666666-6', '00000000-0']:
                return self.env.ref('l10n_cl_fe.par_cfa')
        giro_id = self.env['sii.activity.description'].search([('name', '=', data.get('Giro%s'%type, 'Boleta'))])
        if not giro_id:
            giro_id = self.env['sii.activity.description'].create({
                'name': data.get('Giro%s'%type, 'Boleta'),
            })
        type = 'Emisor'
        dest = 'Origen'
        rut_path = 'RUTEmisor'
        if self.type == 'ventas':
            type = "Receptor"
            dest = 'Recep'
            rut_path = 'RUTRecep'
        rut = self.format_rut(data[rut_path])
        name = (data.get('RznSoc') or data.get('RznSocEmisor')) if self.type=="compras" else data['RznSocRecep']
        data = {
            'name': name,
            'activity_description': giro_id.id,
            'vat': rut,
            'document_type_id': self.env.ref('l10n_cl_fe.dt_RUT').id,
            'responsability_id': self.env.ref('l10n_cl_fe.res_IVARI').id,
            'document_number': data[rut_path],
            'street': data['Dir%s'%dest],
            'city': data.get('Ciudad%s'%dest, ''),
            'company_type': 'company',
        }
        if 'CorreoEmisor' in data or 'CorreRecep' in data:
            data.update(
                {
                    'email': data['CorreoEmisor'] if self.type == 'compras' else data['CorreoRecep'],
                    'dte_email': data['CorreoEmisor'] if self.type == 'compras' else data['CorreoRecep'],
                }
            )
        if self.type == 'compras':
            data.update({'supplier': True})
        partner_id = self.env['res.partner'].create(data)
        return partner_id

    def _default_category(self,):
        md = self.env['ir.model.data']
        res = False
        try:
            res = md.get_object_reference('product', 'product_category_all')[1]
        except ValueError:
            res = False
        return res

    def _buscar_impuesto(self, name="Impuesto", amount=0, sii_code=0, sii_type=False, IndExe=False):
        query = [
            ('amount', '=', amount),
            ('sii_code', '=', sii_code),
            ('type_tax_use', '=', ('purchase' if self.type == 'compras' else 'sale')),
            ('activo_fijo', '=', False),
        ]
        if IndExe:
            query.append(
                    ('sii_type', '=', False)
            )
        if amount == 0 and sii_code == 0 and not IndExe:
            query.append(
                    ('name', '=', name)
            )
        if sii_type:
            query.extend([
                ('sii_type', '=', sii_type),
            ])
        imp = self.env['account.tax'].search(query)
        if not imp:
            imp = self.env['account.tax'].sudo().create({
                'amount': amount,
                'name': name,
                'sii_code': sii_code,
                'sii_type': sii_type,
                'type_tax_use': 'purchase' if self.type == 'compras' else 'sale',
            })
        return imp

    def get_product_values(self, line, price_included=False):
        IndExe = line.find("IndExe")
        amount = 0
        sii_code = 0
        sii_type = False
        if not IndExe:
            amount = 19
            sii_code = 14
            sii_type = False
        imp = self._buscar_impuesto(amount=amount, sii_code=sii_code, sii_type=sii_type, IndExe=IndExe)
        price = float(line.find("PrcItem").text if line.find("PrcItem") is not None else line.find("MontoItem").text)
        if price_included:
            price = imp.compute_all(price, self.env.user.company_id.currency_id, 1)['total_excluded']
        values = {
            'sale_ok': (self.type == 'ventas'),
            'name': line.find("NmbItem").text,
            'lst_price': price,
            'categ_id': self._default_category(),
            'taxes_id': [(6, 0, imp.ids)],
            'supplier_taxes_id': [(6, 0, imp.ids)],
        }
        for c in line.findall("CdgItem"):
            VlrCodigo = c.find("VlrCodigo").text
            if c.find("TpoCodigo").text == 'ean13':
                values['barcode'] = VlrCodigo
            else:
                values['default_code'] = VlrCodigo
        return values

    def _create_prod(self, data, price_included=False):
        product_id = self.env['product.product'].create(self.get_product_values(data, price_included))
        return product_id

    def _buscar_producto(self, document_id, line, price_included=False):
        default_code = False
        CdgItem = line.find("CdgItem")
        NmbItem = line.find("NmbItem").text
        if NmbItem.isspace():
            NmbItem = 'Producto Genérico'
        if document_id:
            code = ' ' + etree.tostring(CdgItem).decode() if CdgItem is not None else ''
            line_id = self.env['mail.message.dte.document.line'].search(
                [
                    '|',
                    ('new_product', '=', NmbItem + '' + code),
                    ('product_description', '=', line.find("DescItem").text if line.find("DescItem") is not None else NmbItem),
                    ('document_id', '=', document_id.id)
                ]
            )
            if line_id:
                if line_id.product_id:
                    return line_id.product_id.id
            else:
                return False
        query = False
        product_id = False
        if CdgItem is not None:
            for c in line.findall("CdgItem"):
                VlrCodigo = c.find("VlrCodigo")
                if VlrCodigo is None or VlrCodigo.text is None or\
                        VlrCodigo.text.isspace():
                    continue
                TpoCodigo = c.find("TpoCodigo").text
                if TpoCodigo == 'ean13':
                    query = [('barcode', '=', VlrCodigo.text)]
                elif TpoCodigo == 'INT1':
                    query = [('default_code', '=', VlrCodigo.text)]
                default_code = VlrCodigo.text
        if not query:
            query = [('name', '=', NmbItem)]
        product_id = self.env['product.product'].search(query)
        query2 = [('name', '=', document_id.partner_id.id)]
        if default_code:
            query2.append(('product_code', '=', default_code))
        else:
            query2.append(('product_name', '=', NmbItem))
        product_supplier = False
        if not product_id and self.type == 'compras':
            product_supplier = self.env['product.supplierinfo'].search(query2)
            if product_supplier and not product_supplier.product_tmpl_id.active:
                raise UserError(_('Plantilla Producto para el proveedor marcado como archivado'))
            product_id = product_supplier.product_id or product_supplier.product_tmpl_id.product_variant_id
            if not product_id:
                if not self.pre_process:
                    product_id = self._create_prod(line, price_included)
                else:
                    code = ''
                    coma = ''
                    for c in line.findall("CdgItem"):
                        code += coma + c.find("TpoCodigo").text + ' ' + c.find("VlrCodigo").text
                        coma = ', '
                    return NmbItem + '' + code
        elif self.type == 'ventas' and not product_id:
            product_id = self._create_prod(line, price_included)
        if not product_supplier and document_id.partner_id and self.type == 'compras':
            price = float(line.find("PrcItem").text if line.find("PrcItem") is not None else line.find("MontoItem").text)
            if price_included:
                price = product_id.supplier_taxes_id.compute_all(price, self.env.user.company_id.currency_id, 1)['total_excluded']
            supplier_info = {
                'name': document_id.partner_id.id,
                'product_name': NmbItem,
                'product_code': default_code,
                'product_tmpl_id': product_id.product_tmpl_id.id,
                'price': price,
                'product_id': product_id.id,
            }
            self.env['product.supplierinfo'].create(supplier_info)
        if not product_id.active:
                raise UserError(_('Producto para el proveedor marcado como archivado'))
        return product_id.id

    def _prepare_line(self, line, document_id, account_id, type, price_included=False):
        data = {}
        product_id = self._buscar_producto(document_id, line, price_included)
        if isinstance(product_id, int):
            data.update(
                {
                    'product_id': product_id,
                }
            )
        elif not product_id:
            return False
        if line.find("MntExe") is not None:
            price_subtotal = float(line.find("MntExe").text)
        else :
            price_subtotal = float(line.find("MontoItem").text)
        discount = 0
        if line.find("DescuentoPct") is not None:
            discount = float(line.find("DescuentoPct").text)
        price = float(line.find("PrcItem").text) if line.find("PrcItem") is not None else price_subtotal
        DescItem = line.find("DescItem")
        data.update({
            'name':  DescItem.text if DescItem is not None else line.find("NmbItem").text,
            'price_unit': price,
            'discount': discount,
            'quantity': line.find("QtyItem").text if line.find("QtyItem") is not None else 1,
            'account_id': account_id,
            'price_subtotal': price_subtotal,
        })
        if self.pre_process and self.type == 'compras':
            data.update({
                'new_product': product_id,
                'product_description': DescItem.text if DescItem is not None else '',
            })
        else:
            product_id = self.env['product.product'].browse(product_id)
            if price_included:
                price = product_id.supplier_taxes_id.compute_all(price, self.env.user.company_id.currency_id, 1)['total_excluded']
                price_subtotal = product_id.supplier_taxes_id.compute_all(price_subtotal, self.env.user.company_id.currency_id, 1)['total_excluded']
            data.update({
                'invoice_line_tax_ids': [(6, 0, product_id.supplier_taxes_id.ids)],
                'uom_id': product_id.uom_id.id,
                'price_unit': price,
                'price_subtotal': price_subtotal,
                })
            if not product_id:
                IndExe = line.find("IndExe")
                amount = 0
                sii_code = 0
                sii_type = False
                if not IndExe:
                    amount = 19
                    sii_code = 14
                    sii_type = False
                imp = self._buscar_impuesto(amount=amount, sii_code=sii_code, sii_type=sii_type, IndExe=IndExe)
                if imp:
                    data['invoice_line_tax_ids'] = [(6, 0, imp.ids)]
        return [0,0, data]

    def _create_tpo_doc(self, TpoDocRef, RazonRef=''):
        vals = {
                'name': RazonRef + ' ' + str(TpoDocRef)
            }
        if str(TpoDocRef).isdigit():
            vals.update({
                    'sii_code': TpoDocRef,
                })
        else:
            vals.update({
                    'doc_code_prefix': TpoDocRef,
                    'sii_code': 801,
                    'use_prefix': True,
                })
        return self.env['sii.document_class'].create(vals)

    def _prepare_ref(self, ref):
        query = []
        TpoDocRef = ref.find("TpoDocRef").text
        RazonRef = ref.find("RazonRef")
        if str(TpoDocRef).isdigit():
            query.append(('sii_code', '=', TpoDocRef))
            query.append(('use_prefix', '=', False))
        else:
            query.append(('doc_code_prefix', '=', TpoDocRef))
        tpo = self.env['sii.document_class'].search(query, limit=1)
        if not tpo:
            tpo = self._create_tpo_doc(TpoDocRef, RazonRef)
        return [0, 0, {
            'origen': ref.find("FolioRef").text,
            'sii_referencia_TpoDocRef': tpo.id,
            'sii_referencia_CodRef': ref.find("CodRef").text if ref.find("CodRef") is not None else None,
            'motivo': RazonRef.text if RazonRef is not None else None,
            'fecha_documento': ref.find("FchRef").text if ref.find("FchRef") is not None else None,
        }]

    def process_dr(self, dr):
        data = {
                    'type': dr.find("TpoMov").text,
                }
        disc_type = "percent"
        if dr.find("TpoValor").text == '$':
            disc_type = "amount"
        data['gdr_type'] = disc_type
        data['valor'] = dr.find("ValorDR").text
        data['gdr_dtail'] = dr.find("GlosaDR").text if dr.find("GlosaDR") is not None else 'Descuento globla'
        return data

    def _prepare_invoice(self, documento, company_id, journal_document_class_id):
        type = 'Emisor'
        rut_path = 'RUTEmisor'
        if self.type == 'ventas':
            type = "Receptor"
            rut_path = 'RUTRecep'
        Encabezado = documento.find("Encabezado")
        IdDoc = Encabezado.find("IdDoc")
        Emisor = Encabezado.find(type)
        RUT = Emisor.find(rut_path).text
        string = etree.tostring(documento)
        dte = xmltodict.parse(string)['Documento']
        invoice = {
                'account_id': False,
            }
        partner_id = self.env['res.partner'].search(
            [
                ('active', '=', True),
                ('parent_id', '=', False),
                ('vat', '=', self.format_rut(RUT))
            ]
        )
        if not partner_id:
            partner_id = self._create_partner(dte['Encabezado'][type])
        elif not partner_id.supplier and self.type == "compras":
            partner_id.supplier = True
        invoice['type'] = 'in_invoice'
        if self.type == "ventas":
            invoice['type'] = 'out_invoice'
        if dte['Encabezado']['IdDoc']['TipoDTE'] in ['54', '61']:
            invoice['type'] = 'in_refund'
            if self.type == "ventas":
                invoice["type"] = "out_refund"
        if partner_id:
            account_id = partner_id.property_account_payable_id.id or journal_document_class_id.journal_id.default_debit_account_id.id
            if invoice['type'] in ('out_invoice', 'in_refund'):
                account_id = partner_id.property_account_receivable_id.id or journal_document_class_id.journal_id.default_credit_account_id.id
            invoice.update(
            {
                'account_id': account_id,
                'partner_id': partner_id.id,
            })
            partner_id = partner_id.id
        try:
            name = self.filename.decode('ISO-8859-1').encode('UTF-8')
        except:
            name = self.filename.encode('UTF-8')
        ted_string = b''
        if documento.find("TED") is not None:
            ted_string = etree.tostring(documento.find("TED"), method="c14n", pretty_print=False)
        FchEmis = IdDoc.find("FchEmis").text
        xml_envio = self.env['sii.xml.envio'].create(
            {
                'name': 'ENVIO_%s' % name.decode(),
                'xml_envio': string.decode(),
                'state': 'Aceptado',
            }
        )
        invoice.update({
            'origin': 'XML Envío: ' + name.decode(),
            'date_invoice': FchEmis,
            'partner_id': partner_id,
            'company_id': company_id.id,
            'journal_id': journal_document_class_id.journal_id.id,
            'sii_xml_request': xml_envio.id,
            'sii_barcode': ted_string.decode(),
        })
        DscRcgGlobal = documento.findall("DscRcgGlobal")
        if DscRcgGlobal:
            drs = [(5,)]
            for dr in DscRcgGlobal:
                drs.append((0, 0, self.process_dr(dr)))
            invoice.update({
                    'global_descuentos_recargos': drs,
                })
        Folio = IdDoc.find("Folio").text
        if partner_id and not self.pre_process and self.type == 'compras':
            invoice.update({
                'reference': Folio,
                'journal_document_class_id': journal_document_class_id.id,
            })
        elif self.type == 'ventas':
            invoice.update({
                'sii_document_number': Folio,
                'journal_document_class_id': journal_document_class_id.id,
                'state': 'open',
                'move_name': '%s%s' % (journal_document_class_id.sii_document_class_id.doc_code_prefix, Folio),
            })
        else:
            RznSoc = Emisor.find('RznSoc')
            if RznSoc is None:
                RznSoc = Emisor.find('RznSocEmisor')
            invoice.update({
                'number': Folio,
                'date': FchEmis,
                'new_partner': RUT + ' ' + RznSoc.text,
                'sii_document_class_id': journal_document_class_id.sii_document_class_id.id,
                'amount': dte['Encabezado']['Totales']['MntTotal'],
            })
        return invoice

    def _get_journal(self, sii_code, company_id):
        type = 'purchase'
        if self.type == 'ventas':
            type = 'sale'
        journal_sii = self.env['account.journal.sii_document_class'].search(
            [
                ('sii_document_class_id.sii_code', '=', sii_code),
                ('journal_id.type', '=', type),
                ('journal_id.company_id', '=', company_id.id)
            ],
            limit=1,
        )
        return journal_sii

    def _get_invoice_lines(self, documento, document_id, account_id, invoice_type, price_included):
        lines = []
        for line in documento.findall("Detalle"):
            new_line = self._prepare_line(line, document_id, account_id, invoice_type, price_included)
            if new_line:
                lines.append(new_line)
        return lines

    def _get_data(self, documento, company_id):
        string = etree.tostring(documento)
        dte = xmltodict.parse(string)['Documento']
        Encabezado = documento.find("Encabezado")
        IdDoc = Encabezado.find("IdDoc")
        price_included = Encabezado.find("MntBruto")
        journal_document_class_id = self._get_journal(
                    IdDoc.find("TipoDTE").text,
                    company_id)
        if not journal_document_class_id:
            sii_document_class = self.env['sii.document_class'].search([
                            ('sii_code', '=', IdDoc.find("TipoDTE").text)
                            ])
            raise UserError('No existe Diario para el tipo de documento %s, por favor añada uno primero, o ignore el documento' % sii_document_class.name.encode('UTF-8'))
        data = self._prepare_invoice(
                    documento,
                    company_id,
                    journal_document_class_id)
        lines = [(5,)]
        document_id = self._dte_exist(documento)
        lines.extend(self._get_invoice_lines(
                    documento,
                    document_id,
                    data['account_id'],
                    data['type'],
                    price_included))
        product_id = self.env['product.product'].search([
                ('product_tmpl_id', '=', self.env.ref('l10n_cl_fe.product_imp').id),
            ]
        ).id
        if 'ImptoReten' in dte['Encabezado']['Totales']:
            Totales = dte['Encabezado']['Totales']
            if 'TipoImp' in Totales['ImptoReten']:
                Totales = [Totales['ImptoReten']['TipoImp']]
            else:
                Totales = Totales['ImptoReten']
            for i in Totales:
                imp = self._buscar_impuesto(
                                name="OtrosImps_" + str(i['TipoImp']),
                                sii_code=i['TipoImp'])
                price = float(i['MontoImp'])
                price_subtotal = float(i['MontoImp'])
                if price_included:
                    price = imp.compute_all(price, self.env.user.company_id.currency_id, 1)['total_excluded']
                    price_subtotal = imp.compute_all(price_subtotal, self.env.user.company_id.currency_id, 1)['total_excluded']
                lines.append([0, 0, {
                    'invoice_line_tax_ids': ((6, 0, imp.ids)) ,
                    'product_id': product_id,
                    'name': 'MontoImpuesto %s' % str(i['TipoImp']),
                    'price_unit': price,
                    'quantity': 1,
                    'price_subtotal': price_subtotal,
                    'account_id':  journal_document_class_id.journal_id.default_debit_account_id.id
                    }]
                )
        #if 'IVATerc' in dte['Encabezado']['Totales']:
        #    imp = self._buscar_impuesto(name="IVATerc" )
        #    lines.append([0,0,{
        #        'invoice_line_tax_ids': [ imp ],
        #        'product_id': product_id,
        #        'name': 'MontoImpuesto IVATerc' ,
        #        'price_unit': dte['Encabezado']['Totales']['IVATerc'],
        #        'quantity': 1,
        #        'price_subtotal': dte['Encabezado']['Totales']['IVATerc'],
        #        'account_id':  journal_document_class_id.journal_id.default_debit_account_id.id
        #        }]
        #    )
        Referencias = documento.findall("Referencia")
        if not self.pre_process and Referencias:
            refs = [(5,)]
            for ref in Referencias:
                refs.append(self._prepare_ref(ref))
            data['referencias'] = refs
        data['invoice_line_ids'] = lines
        mnt_neto = int(dte['Encabezado']['Totales']['MntNeto']) if 'MntNeto' in dte['Encabezado']['Totales'] else 0
        mnt_neto += int(dte['Encabezado']['Totales']['MntExe']) if 'MntExe' in dte['Encabezado']['Totales'] else 0
        data['amount_untaxed'] = mnt_neto
        data['amount_total'] = dte['Encabezado']['Totales']['MntTotal']
        if document_id:
            purchase_to_done = False
            if document_id.purchase_to_done:
                purchase_to_done = document_id.purchase_to_done.ids()
            if purchase_to_done:
                data['purchase_to_done'] = purchase_to_done
        return data

    def _inv_exist(self, documento):
        encabezado = documento.find("Encabezado")
        Emisor = encabezado.find("Emisor")
        IdDoc = encabezado.find("IdDoc")
        type = ['in_invoice', 'in_refund']
        if self.type == 'ventas':
            type = ['out_invoice', 'out_refund']
        return self.env['account.invoice'].search(
            [
                ('reference', '=', IdDoc.find("Folio").text),
                ('type', 'in', type),
                ('document_class_id.sii_code', '=', IdDoc.find("TipoDTE").text),
                ('partner_id.vat', '=', self.format_rut(Emisor.find("RUTEmisor").text)),
            ])

    def _create_inv(self, documento, company_id):
        inv = self._inv_exist(documento)
        if inv:
            return inv
        Totales = documento.find("Encabezado/Totales")
        data = self._get_data(documento, company_id)
        inv = self.env['account.invoice'].create(data)
        monto_xml = float(Totales.find('MntTotal').text)
        if inv.amount_total == monto_xml:
            return inv
        inv.amount_total = monto_xml
        for t in inv.tax_line_ids:
            if Totales.find('TasaIVA') is not None and t.tax_id.amount == float(Totales.find('TasaIVA').text):
                t.amount = float(Totales.find('IVA').text)
                t.base = float(Totales.find('MntNeto').text)
            else:
                t.base = float(Totales.find('MntExe').text)
        return inv

    def _dte_exist(self, documento):
        encabezado = documento.find("Encabezado")
        Emisor = encabezado.find("Emisor")
        IdDoc = encabezado.find("IdDoc")
        new_partner = Emisor.find("RUTEmisor").text
        if Emisor.find("RznSoc") is not None:
            new_partner += ' ' + Emisor.find("RznSoc").text
        else:
            new_partner += ' ' + Emisor.find("RznSocEmisor").text
        return self.env['mail.message.dte.document'].search(
            [
                ('number', '=', IdDoc.find("Folio").text),
                ('sii_document_class_id.sii_code', '=', IdDoc.find("TipoDTE").text),
                '|',
                ('partner_id.vat', '=', self.format_rut(Emisor.find("RUTEmisor").text)),
                ('new_partner', '=', new_partner),
            ]
        )

    def _create_pre(self, documento, company_id):
        dte = self._dte_exist(documento)
        if dte:
            _logger.warning(_("El documento %s ya se encuentra registrado" % dte.name ))
            return dte
        data = self._get_data(documento, company_id)
        data.update({
            'dte_id': self.dte_id.id,
        })
        return self.env['mail.message.dte.document'].create(data)

    def _get_dtes(self):
        xml = self._read_xml('etree')
        if xml.tag == 'SetDTE':
            return xml.findall("DTE")
        envio = xml.find("SetDTE")
        if envio is None:
            if xml.tag == "DTE":
                return [xml]
            return []
        return envio.findall("DTE")

    def do_create_pre(self):
        created = []
        resp = self.do_receipt_deliver()
        dtes = self._get_dtes()
        for dte in dtes:
            try:
                documento = dte.find("Documento")
                company_id = self.env['res.company'].search(
                        [
                            ('vat', '=', self.format_rut(documento.find("Encabezado/Receptor/RUTRecep").text)),
                        ],
                        limit=1,
                    )
                if not company_id:
                    _logger.warning("No existe compañia para %s" %documento.find("Encabezado/Receptor/RUTRecep").text)
                    continue
                pre = self._create_pre(
                    documento,
                    company_id,
                )
                if pre:
                    inv = self._inv_exist(documento)
                    pre.write({
                        'xml': etree.tostring(dte),
                        'invoice_id': inv.id,
                        }
                    )
                    created.append(pre.id)
            except Exception as e:
                _logger.warning('Error en 1 factura con error:  %s' % str(e))
        return created

    def do_create_inv(self):
        created = []
        dtes = self._get_dtes()
        for dte in dtes:
            try:
                company_id = self.document_id.company_id
                documento = dte.find("Documento")
                path_rut = "Encabezado/Receptor/RUTRecep"
                if self.type == 'ventas':
                    path_rut = "Encabezado/Emisor/RUTEmisor"
                company_id = self.env['res.company'].search(
                        [
                            ('vat', '=', self.format_rut(documento.find(path_rut).text)),
                        ],
                        limit=1,
                    )
                inv = self._create_inv(
                    documento,
                    company_id,
                )
                if self.document_id:
                    self.document_id.invoice_id = inv.id
                if inv:
                    created.append(inv.id)
                if not inv:
                    raise UserError('El archivo XML no contiene documentos para alguna empresa registrada en Odoo, o ya ha sido procesado anteriormente ')
                if self.type == 'ventas' or self.option == 'accept':
                    inv._onchange_invoice_line_ids()
                    inv._onchange_partner_id()
                    inv.action_move_create()
                    guardar = {
                        'document_class_id': inv.document_class_id.id,
                        'sii_document_number': inv.sii_document_number
                    }
                    inv.move_id.write(guardar)
            except Exception as e:
                _logger.warning('Error en crear 1 factura con error:  %s' % str(e))
        if created and self.option not in [False, 'upload'] and self.type == 'compras':
            wiz_accept = self.env['sii.dte.validar.wizard'].create(
                {
                    'invoice_ids': [(6, 0, created)],
                    'action': 'validate',
                    'option': self.option,
                }
            )
            wiz_accept.confirm()
        return created

    def prepare_purchase_line(self, line, document_id, date_planned, price_included=False):
        product = self._buscar_producto(document_id, line, price_included)
        if not product:
            return False
        if isinstance(product, int):
            product = self.env['product.product'].browse(product)
        if line.find("MntExe") is not None:
            price_subtotal = float(line.find("MntExe").text)
        else:
            price_subtotal = float(line.find("MontoItem").text)
        discount = 0
        if line.find("DescuentoPct") is not None:
            discount = float(line.find("DescuentoPct").text)
        price = float(line.find("PrcItem").text) if line.find("PrcItem") is not None else price_subtotal
        DescItem = line.find("DescItem")
        values = {
            'name': DescItem.text if DescItem is not None else line.find("NmbItem").text,
            'product_id': product.id,
            'product_uom': product.uom_id.id,
            'taxes_id': [(6, 0, product.supplier_taxes_id.ids)],
            'price_unit': price,
            'discount': discount,
            'product_qty': line.find("QtyItem").text if line.find("QtyItem") is not None else 1,
            'date_planned': date_planned,
        }
        return (0, 0, values)

    def _purchase_exist(self, purchase_vals, partner):
        purchase_model = self.env['purchase.order']
        #antes de crear la OC, verificar que no exista otro documento con los mismos datos
        other_orders = purchase_model.search([
            ('partner_id', '=', purchase_vals['partner_id']),
            ('partner_ref', '=', purchase_vals['partner_ref']),
            ('company_id', '=', purchase_vals['company_id']),
            ])
        if other_orders:
            raise UserError("Ya existe un Pedido de compra con Referencia: %s para el Proveedor: %s.\n" \
                            "No se puede crear nuevamente, por favor verifique." %
                            (purchase_vals['partner_ref'], partner.name))

    def _prepare_purchase(self, documento, company, partner):
        Encabezado = documento.find("Encabezado")
        IdDoc = Encabezado.find("IdDoc")
        purchase_vals = {
            'partner_ref': IdDoc.find("Folio").text,
            'date_order': IdDoc.find("FchEmis").text,
            'partner_id': partner.id,
            'company_id': company.id,
        }
        return purchase_vals

    def _create_po(self, documento, company):
        purchase_model = self.env['purchase.order']
        path_rut = "Encabezado/Emisor/RUTEmisor"
        RUT = documento.find(path_rut).text
        string = etree.tostring(documento)
        dte = xmltodict.parse(string)['Documento']
        Encabezado = documento.find("Encabezado")
        price_included = Encabezado.find("MntBruto")
        partner = self.env['res.partner'].search([
            ('active', '=', True),
            ('parent_id', '=', False),
            ('vat', '=', self.format_rut(RUT)),
        ])
        if not partner:
            partner = self._create_partner(dte['Encabezado']['Emisor'])
        elif not partner.supplier:
            partner.supplier = True
        purchase_vals = self._prepare_purchase(documento, company, partner)
        self._purchase_exist(purchase_vals, partner)
        document_id = self._dte_exist(documento)
        lines = [(5,)]
        for line in documento.findall("Detalle"):
            new_line = self.prepare_purchase_line(line, document_id, purchase_vals['date_order'], price_included=price_included)
            if new_line:
                lines.append(new_line)
        if not lines:
            _logger.warning("No se pudo crear el Pedido de compra xq no hay lineas, verifique si los productos existen en su sistema")
            return False
        purchase_vals['order_line'] = lines
        po = purchase_model.create(purchase_vals)
        po.button_confirm()
        inv = self.env['account.invoice'].search([('purchase_id', '=', po.id)])
        #inv.sii_document_class_id = dte['Encabezado']['IdDoc']['TipoDTE']
        return po

    def do_create_po(self):
        #self.validate()
        dtes = self._get_dtes()
        for dte in dtes:
            documento = dte.find("Documento")
            path_rut = "Encabezado/Receptor/RUTRecep"
            company = self.env['res.company'].search([
                ('vat', '=', self.format_rut(documento.find(path_rut).text)),
                ], limit=1)
            tipo_dte = documento.find("Encabezado/IdDoc/TipoDTE").text
            if tipo_dte in ['34', '33']:
                self._create_po(documento, company)
            elif tipo_dte in ['56', '61']: # es una nota
                self._create_inv(documento, company)

