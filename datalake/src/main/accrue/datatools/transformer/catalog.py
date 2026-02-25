import enum

from accrue.datatools.transformer.interface import TransformerInterface
from accrue.datatools.transformer._audit_logs import AuditLogsTransformer
from accrue.datatools.transformer._checkout_payments import CheckoutPaymentsTransformer
from accrue.datatools.transformer._payment_events import PaymentEventsTransformer
from accrue.datatools.transformer._merchant_risk_report import MerchantDailyRiskReportTransformer


class TransformerCatalog(enum.Enum):
    AUDIT_LOGS = AuditLogsTransformer
    CHECKOUT_PAYMENTS = CheckoutPaymentsTransformer
    PAYMENT_EVENTS = PaymentEventsTransformer
    MERCHANT_DAILY_RISK_REPORTS = MerchantDailyRiskReportTransformer

    def __call__(self, **kwargs) -> TransformerInterface:
        return self.value(**kwargs)


__all__ = ["TransformerCatalog"]
