from accrue.datatools.dao.service._delta import DeltaService
from accrue.datatools.dao.service._postgres import PostgresService
from accrue.datatools.transformer.catalog import TransformerCatalog


svc = DeltaService.auto()
transformer = TransformerCatalog.MERCHANT_DAILY_RISK_REPORTS(
    source_tables=[
        "silver/payment_events_clean",
        "silver/checkout_payments_clean",
        "silver/audit_logs_clean",
    ],
    target_table="gold/merchant_daily_risk_reports",
    source_service=svc,
    target_service=svc,
)

df = transformer.run()

# --- Sync Gold Delta → Postgres (serving layer) ---
print("  Syncing gold/merchant_daily_risk_reports → Postgres...")
pg = PostgresService.auto()
pg.write(table="merchant_daily_risk_reports", data=df, mode="replace")
print("  ✓ merchant_daily_risk_reports synced to Postgres.")
print("Gold layer complete.")

print(df)