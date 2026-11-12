# Vendored Chart.js (not in Git until you add it)

The Laundrix Content Security Policy only allows same-origin scripts, so Chart.js is served from this folder
rather than a CDN. Download **one** file, once:

    Chart.js 4.4.7  ->  chart.umd.js   (MIT licence; the licence header is inside the file)

PowerShell, from the project root:

    Invoke-WebRequest "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.js" `
        -OutFile "app/analytics/static/vendor/chart.umd.js"

Check it: the first line of the file should contain `Chart.js v4.4.7`.
Commit the file with the rest of the feature (it is intentionally NOT git-ignored).
If the file is missing the page still works: charts are replaced by a notice and every
chart's data table opens automatically.
