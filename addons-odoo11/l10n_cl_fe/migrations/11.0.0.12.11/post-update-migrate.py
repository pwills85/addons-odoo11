# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, installed_version):
    _logger.warning('Post Migrating l10n_cl_fe from version %s to 11.0.0.12.11' % installed_version)
    cr.execute("ALTER TABLE res_users DROP COLUMN key_file_temp, DROP COLUMN filename_temp, DROP COLUMN cert_temp, DROP COLUMN priv_temp, DROP COLUMN expire_temp, DROP COLUMN emision_temp, DROP COLUMN serial_temp")
    cr.execute("ALTER TABLE res_company DROP COLUMN key_file_temp, DROP COLUMN filename_temp, DROP COLUMN cert_temp, DROP COLUMN priv_temp, DROP COLUMN expire_temp, DROP COLUMN emision_temp, DROP COLUMN serial_temp")
    cr.execute("DROP TABLE back_res_c")
