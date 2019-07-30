# -*- coding: utf-8 -*-
from odoo import fields, models, api
from odoo.tools.translate import _
import ast
from datetime import datetime
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT as DTF
import logging
_logger = logging.getLogger(__name__)


class ColaEnvio(models.Model):
    _name = "sii.cola_envio"

    doc_ids = fields.Char(
            string="Id Documentos",
        )
    model = fields.Char(
            string="Model destino",
        )
    user_id = fields.Many2one(
            'res.users',
        )
    tipo_trabajo = fields.Selection(
            [
                    ('pasivo', 'pasivo'),
                    ('envio', 'Envío'),
                    ('consulta', 'Consulta')
            ],
            string="Tipo de trabajo",
        )
    active = fields.Boolean(
            string="Active",
            default=True,
        )
    n_atencion = fields.Char(
            string="Número atención",
        )
    date_time = fields.Datetime(
            string='Auto Envío al SII',
        )
    send_email = fields.Boolean(
            string="Auto Enviar Email",
            default=False,
        )

    def enviar_email(self, doc):
        doc.send_exchange()

    def es_boleta(self, doc):
        if hasattr(doc, 'document_class_id'):
            return doc.document_class_id.es_boleta()
        return False

    def _es_doc(self, doc):
        if hasattr(doc, 'sii_message'):
            return doc.sii_message
        return True

    def _procesar_tipo_trabajo(self):
        if not self.user_id.active:
            _logger.warning("¡Usuario %s desactivado!" % self.user_id.name)
            return
        docs = self.env[self.model].sudo(self.user_id.id).browse(ast.literal_eval(self.doc_ids))
        if self.tipo_trabajo == 'pasivo':
            if docs[0].sii_xml_request and docs[0].sii_xml_request.state in ['Aceptado', 'Enviado', 'Rechazado', 'Anulado']:
                self.unlink()
                return
            if self.date_time and datetime.now() >= datetime.strptime(self.date_time, DTF):
                try:
                    envio_id = docs.do_dte_send(self.n_atencion)
                    if envio_id.sii_send_ident:
                        self.tipo_trabajo = 'consulta'
                except Exception as e:
                    _logger.warning('Error en Envío automático')
                    _logger.warning(str(e))
                docs.get_sii_result()
            return
        if (self._es_doc(docs[0]) or self.es_boleta(docs[0])) and docs[0].sii_result in ['Proceso', 'Reparo', 'Rechazado', 'Anulado']:
            if self.send_email and docs[0].sii_result in ['Proceso', 'Reparo']:
                for doc in docs:
                    self.enviar_email(doc)
            self.unlink()
            return
        if self.tipo_trabajo == 'consulta':
            try:
                docs.ask_for_dte_status()
            except Exception as e:
                _logger.warning("Error en Consulta")
                _logger.warning(str(e))
        elif self.tipo_trabajo == 'envio' and (not docs[0].sii_xml_request or not docs[0].sii_xml_request.sii_send_ident or docs[0].sii_xml_request.state not in ['Aceptado', 'Enviado']):
            try:
                envio_id = docs.with_context(user=self.user_id.id).do_dte_send(self.n_atencion)
                if envio_id.sii_send_ident:
                    self.tipo_trabajo = 'consulta'
                docs.get_sii_result()
            except Exception as e:
                _logger.warning("Error en envío Cola")
                _logger.warning(str(e))
        elif self.tipo_trabajo == 'envio' and docs[0].sii_xml_request and (docs[0].sii_xml_request.sii_send_ident or docs[0].sii_xml_request.state in [ 'Aceptado', 'Enviado', 'Rechazado']):
            self.tipo_trabajo = 'consulta'


    @api.model
    def _cron_procesar_cola(self):
        ids = self.search([('active', '=', True)])
        if ids:
            for c in ids:
                c._procesar_tipo_trabajo()
