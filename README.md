# Denmart — V11

Canonical portals:
- Customer: `/`
- Merchant/POS: `/merchant` then `/merchant/on`
- Master admin: `/control` (login and dashboard in the same protected portal)

The admin login form includes CSRF protection and successful owner authentication redirects directly to `/control`. Legacy portal aliases are not part of the new UI.

The catalogue uses broad supermarket departments and a Kenyan-oriented starter assortment. Availability is admin-controlled: customers and POS only see enabled, in-stock store products.
