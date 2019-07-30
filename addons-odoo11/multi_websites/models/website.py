# -*- coding: utf-8 -*-
#################################################################################
#
#   Copyright (c) 2017-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#   See LICENSE URL <https://store.webkul.com/license.html/> for full copyright and licensing details.
#################################################################################
import base64
import os
import re
from odoo import api, fields, models, tools, _
from odoo.tools import config
from odoo.exceptions import UserError
from lxml import etree
import logging
from odoo.http import request
_logger = logging.getLogger(__name__)

TECHNICAL_NAME = "multi_websites"
MULTI_LAYOUT = TECHNICAL_NAME + ".multi_website_layout_%d"
MULTI_ASSETS = TECHNICAL_NAME + ".multi_website_assets_%d"
MULTI_VIEW = TECHNICAL_NAME + ".multi_website_view_%d_%d"

class Website(models.Model):

    _inherit = 'website'

    def _get_logo(self):
        return base64.b64encode(open(os.path.join(tools.config['root_path'], 'addons', 'base', 'res', 'res_company_logo.png'), 'rb') .read())

    def _compute_logo_web(self):
        for website in self:
            website.logo_web = tools.image_resize_image(website.logo, (180, None))


    color = fields.Integer(
        string='Color Index'
    )

    website_categ_id = fields.Many2one(
        comodel_name = 'product.category',
        string = "Category"
    )
    carrier_ids = fields.Many2many(
        comodel_name = 'delivery.carrier',
        string = "Carriers"
    )
    acquirer_ids = fields.Many2many(
        comodel_name = 'payment.acquirer',
        string = "Acquirers"
    )
    website_menu_ids = fields.One2many(
        'website.menu',
        'website_id',
        'Menus'
    )
    logo = fields.Binary(
        default=_get_logo,
        string="Logo")
    logo_web = fields.Binary(
        compute='_compute_logo_web',
        store=True)
    product_pricelist_ids = fields.One2many(
        'product.pricelist',
        'website_id',
        'Price List'
    )
    website_multi_theme_id = fields.Many2one(
        string="Website Theme",
        comodel_name='website.multi.theme',
        domain=[("multi_theme_asset_ids.view_id", "!=", False)],
        help="Theme for this website",
    )
    website_multi_theme_view_ids = fields.One2many(
        comodel_name="ir.ui.view",
        inverse_name="website_id",
        domain=[ ("multi_theme_created", "=", True), "|", ("active", "=", True), ("active", "=", False)],
        string="Multi Website views",
    )

    @api.multi
    def open_related_model_view(self):
        self.ensure_one()
        website_realted_record = self._context.get('website_realted_record')
        website_realted_model =  self._context.get('website_realted_model')
        record_ids = self.read([website_realted_record])[0].get(website_realted_record)
        return {
            'name': ('Data'),
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'tree,form',
            'res_model': website_realted_model,
            'view_id': False,
            'domain': [('id', 'in', record_ids)],
            'target': 'current',
        }
        
    @api.multi
    def open_website_view(self):
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        base_url_list = base_url.split(':')
        res_url  ='%s://%s'%(base_url_list[0],self.domain)
        _logger.info('------base_url_list-----------%r',base_url_list[0])
        _logger.info('------base_url_list-----------%r',base_url_list[-1])
        if  base_url_list[0]!=base_url_list[-1]:
            res_url='%s:%s'%(res_url, base_url_list[-1])
        res_url = "%s/?db=%s" %(res_url, self.env.cr.dbname)
        _logger.info('------base_url-----------%r',base_url)
        _logger.info('------res_url-----------%r',res_url)
        client_action = {
            'type': 'ir.actions.act_url',
            'name': "Website Page",
            'target': 'new',
            'url':res_url,
         }
        return client_action


    @api.multi
    def sale_product_domain(self):
        domain = super(Website,self).sale_product_domain()
        domain+=[('company_id','=',self.company_id.id)]
        website_categ_ids = self.website_categ_id.ids
        if website_categ_ids:
            categ_domain =['|',('id','in',website_categ_ids),('id','child_of',website_categ_ids)]
            categ_ids  =self.env['product.category'].search(categ_domain).ids
            domain+=[('categ_id','in',categ_ids)]
        return domain

    @api.model
    def set_multi_website_data(self):
        pass

    @api.model
    def create(self, vals):
        result = super(Website, self).create(vals)
        if vals.get('website_multi_theme_id'):
            result._activate_website_multi_theme()
        return result

    def write(self, vals):
        result = super(Website, self).write(vals)
        if vals.get('website_multi_theme_id'):
            self._activate_website_multi_theme()
        return result

    def _activate_website_multi_theme(self):
        main_assets_frontend = self.env.ref("web.assets_frontend") | self.env.ref("website.assets_frontend")
        main_layout = self.env.ref("website.layout")
        main_views = main_assets_frontend | main_layout
        mt_assets = self.env.ref("multi_websites.multi_website_assets")
        mt_layout = self.env.ref("multi_websites.multi_website_layout")
        for website in self:
            if not website.website_multi_theme_id:
                website.website_multi_theme_view_ids.unlink()
                continue
            custom_assets = website._duplicate_view_for_website(mt_assets,MULTI_ASSETS % website.id,True)
            custom_layout = website._duplicate_view_for_website( mt_layout,MULTI_LAYOUT % website.id, True)
            custom_assets.arch = mt_assets.arch
            custom_layout.arch = mt_layout.arch.format(theme_view=custom_assets.key)
            custom_views = custom_assets | custom_layout
            custom_views.update({"active": True,})
            for origin_view in website.mapped("website_multi_theme_id.multi_theme_asset_ids.view_id"):
                copied_view = website._duplicate_view_for_website(origin_view,MULTI_VIEW % (website.id, origin_view.id),False)
                if copied_view.inherit_id and copied_view.inherit_id < main_views:
                    data = etree.fromstring(copied_view.arch)
                    if copied_view.inherit_id < main_assets_frontend:
                        copied_view.inherit_id = custom_assets
                        data.attrib["inherit_id"] = custom_assets.key
                    elif copied_view.inherit_id < main_layout:
                        copied_view.inherit_id = custom_layout
                        data.attrib["inherit_id"] = custom_layout.key
                    copied_view.arch = etree.tostring(data)
                custom_views |= copied_view
            (website.website_multi_theme_view_ids - custom_views).unlink()
            
    def _duplicate_view_for_website(self, pattern, xmlid, override_key):
        self.ensure_one()
        try:
            result = self.env.ref(xmlid)
        except ValueError:
            pass
        else:
            if "xml" in config.get("dev_mode"):
                result.arch = pattern.arch
            return result
        key = xmlid if override_key else pattern.key
        result = pattern.copy({
            "active": pattern.active_before,
            "arch_fs": False,
            "customize_show": False,
            "key": key,
            "multi_theme_created": True,
            "name": u"{} (Multi-website {} for {})".format(
                pattern.name,
                xmlid,
                self.display_name,
            ),
            "website_id": self.id,
        })
        
        module, name = xmlid.split(".")
        self.env["ir.model.data"].create({
            "model": result._name,
            "module": module,
            "name": name,
            "noupdate": True,
            "res_id": result.id,
        })
        return result

    @api.model
    def get_current_website(self):
        domain_name = request and request.httprequest.environ.get('HTTP_HOST', '').split(':')[0] or None
        website_id = self._get_current_website_id(domain_name)
        default_website_id = website_id
        if request.session.get('wk_multi_website_id'):
            website_id = int(request.session.get('wk_multi_website_id'))
        request.context = dict(request.context, website_id=website_id)
        # request.session['wk_multi_website_id'] = default_website_id
        return self.browse(website_id)

    @api.multi
    def sale_get_order(self, force_create=False, code=None, update_pricelist=False, force_pricelist=False):
        sale_order = super(Website ,self).sale_get_order(force_create,code, update_pricelist, force_pricelist)
        if sale_order and request.website.id:
            sale_order.wk_website_id = request.website.id
        return sale_order