# REAL MART — separated retail architecture

The current service hostname can be a Render address such as `https://choices-6ej4.onrender.com/` today and a custom domain later. The code never hard-codes the hostname.

## Public customer shop
`/` is the online ordering site. It is intentionally commerce-first: search, branch choice, categories, compact product cards, prices, basket and checkout. There is no POS link, staff link or admin link in the public chrome.

The customer QR encodes the current site origin at request time (`request.url_root`). It therefore follows whichever host is serving the application instead of embedding a permanent Render or `.com` URL.

## Multi-mart mobile install
`/supermarket` is the separate mobile shopping/install entry. The manifest and service worker are scoped to `/supermarket`, so its PWA does not control POS/admin pages. The installed app uses standalone display and therefore does not show browser address controls during normal use.

## POS / cashier application
`/otcOmc` is deliberately not linked from the public shop. An unauthenticated visit goes to `/otcOmc/login`; successful cashiers land directly on the till. The POS PWA service worker is scoped only to `/otcOmc`. `/pos` compatibility routes have been removed.

## Master admin
`/fr%2` is the protected control centre. `/fr%2/login` is its dedicated login. Admin has access to catalogue/prices, marts, users, audit, system errors, security and backups. It is not linked from public or POS navigation.

## Security boundary
Customer requests do not receive the POS UI or staff navigation. POS product lookup and sale endpoints require an authenticated cashier permission and validate store ownership. The public product API does not return stock counts. Online payment requests are checked against the recorded order total, while POS payment initiation requires cashier authorization. Payment credentials stay server-side. Public server errors are replaced with a generic page and recorded in the protected System Errors screen.

## Deployment
Render should use the bundled Postgres service through `DATABASE_URL`. SQLite is local-development only. The app bootstraps missing tables on first start so a new database cannot fail with `no such table: stores`.
