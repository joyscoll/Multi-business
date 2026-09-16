# Denmart — V11

Canonical portals:
- Customer: `/`
- Merchant/POS: `/merchant` then `/merchant/on`
- Master admin: `/control` (login and dashboard in the same protected portal)

The admin login form includes CSRF protection and successful owner authentication redirects directly to `/control`. Legacy portal aliases are not part of the new UI.

The catalogue uses broad supermarket departments and a Kenyan-oriented starter assortment. Availability is admin-controlled: customers and POS only see enabled, in-stock store products.


## Security and recovery

- `/merchant` is a protected merchant login. `/merchant/on` requires both an authenticated staff account and the merchant portal session.
- `/logout` signs out the current authenticated portal and clears the session.
- `/control` is the master administrator login and dashboard.
- Admin **Backups & recovery** provides complete JSON and portable SQLite downloads plus protected restore actions. Restores replace the full database snapshot, including staff accounts and credentials, so the administrator must sign in again afterward.
- Admin **Settings & M-PESA** stores Daraja credentials encrypted at rest, supports PayBill or Till/Buy Goods transaction type, stores the public callback URL, and can test Daraja OAuth credentials without initiating a payment.

For live M-PESA operation, obtain and configure the business credentials in Safaricom Daraja 3.0, then use the protected Settings screen to enter the issued values and registered HTTPS callback. Safaricom describes Daraja 3.0 as its platform for integrating M-PESA APIs.
