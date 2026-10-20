from . import ir_actions_report
from . import res_company
from . import res_config_settings
from . import hr_employee
from . import res_partner
from . import account_move
from . import account_payment
from . import account_analytic_account
from . import ir_attachment
from . import clearance_documents
from . import clearance_rejection
from . import logistics_port
from . import logistics_document_type
from . import logistics_service_type
from . import logistics_reopen_reason
from . import logistics_billing_service
from . import logistics_file
from . import logistics_expense
# after the file, the expense and account.move: it inherits all three
from . import legacy_uploads
# after legacy_uploads: it redefines is_handling on the line and the
# accounts of a migrated line
from . import handling
from . import clearance_turnaround
from . import clearance_task
