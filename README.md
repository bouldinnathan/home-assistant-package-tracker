# Package Tracker for Home Assistant

Paste a tracking number into Home Assistant and get a sensor that tracks it -
UPS, FedEx, DHL, and USPS - with automatic status-change notifications to
your phone (or anywhere else `notify` can reach).

## How it decides who to ask

For each package, this integration resolves a carrier (either the one you
picked when adding it, or a best-effort guess from the tracking number's
shape - see "Carrier auto-detection honesty note" below), then builds an
ordered list of candidate backends and tries them **in order, on every poll,
assuming any one of them can fail**:

1. That carrier's own native API, if you've configured credentials for it
   (Settings -> Devices & Services -> Package Tracker -> Configure ->
   **Carrier API credentials**).
2. [17track](https://www.17track.net), if configured.
3. [AfterShip](https://www.aftership.com), if configured.
4. [TrackingMore](https://www.trackingmore.com), if configured.
5. [Ship24](https://www.ship24.com), if configured.

Whichever of these you've actually configured are tried in that order every
poll cycle; nothing about "this one worked last time" is assumed. If one
raises an error - a timeout, a rejected key, a rate limit, an unrecognized
response shape - it's logged and the next candidate is tried immediately,
same poll cycle. Only if *every configured candidate* fails does the package
fall back to its last known result (fail soft - the sensor doesn't flip to
an error state just because every backend had a bad moment at the same
time). A package reports `needs_configuration` only when there was nothing
to try at all - no native credentials for its carrier and no fallback
aggregator configured.

You don't need all four carriers' native credentials, and you don't need all
four fallback aggregators - configuring 17track alone covers everything with
the least setup, at the cost of depending on a third party and its
free-tier quota (roughly 100 tracking numbers/month as of writing).
Configuring more than one fallback buys resilience against any single
aggregator's outage or quota exhaustion, at the cost of registering more
free accounts. Configuring a carrier's own native API is the most setup (a
free developer account with that carrier) and tries that carrier directly
before any configured third-party fallback on every poll.

Each backend attempt has a 30-second timeout. The last tracking result and
delivery timer are saved locally, so option changes and Home Assistant
restarts preserve the last known status during an outage and do not restart
the auto-archive countdown.

## Carrier auto-detection honesty note

There's no public, authoritative algorithm that maps a tracking number to
its carrier with certainty - length and prefix conventions overlap (a plain
12-digit number, for instance, is ambiguous). Auto-detection
(`custom_components/package_tracker/carrier_detect.py`) uses well-known
format conventions (UPS's `1Z` prefix, USPS's service-type-code prefixes,
DHL's `JJD` prefix, FedEx's typical digit lengths) to make a *best guess*,
not a guarantee. When adding a package, the carrier dropdown defaults to
"Auto-detect" but you can always pick the carrier explicitly - do that if a
package ends up routed to the wrong backend.

Similarly, all eight clients here (the four native carriers and the four
fallback aggregators) are built against each service's currently-published
API documentation, parsed defensively (`.get()` throughout, one bounded
shape check) so that if a service changes a field name, tracking through it
logs a clear error and the coordinator moves on to the next candidate in the
chain, instead of silently returning wrong data or crashing the poll cycle.
If a service's response shape has drifted, please open an issue with the
(redacted) diagnostics download rather than assuming it's your setup.

## Installation

### HACS (recommended)

[Open Package Tracker in HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=bouldinnathan&repository=home-assistant-package-tracker&category=integration)

1. Open the link above and choose **Download** (or add this repo manually in
   HACS -> Integrations -> ⋮ -> Custom repositories, category
   "Integration", then install "Package Tracker" from the list).
2. Restart Home Assistant.

### Manual

Copy `custom_components/package_tracker` into your Home Assistant
`config/custom_components/` directory and restart.

## Setup

1. Settings -> Devices & Services -> Add Integration -> "Package Tracker".
   This just creates the entry - it starts with no carrier credentials and
   no packages.
2. Open the new "Package Tracker" integration card -> **Configure** to reach
   the options menu:
   - **Add a package** - paste a tracking number, optionally override the
     carrier and set a friendly name.
   - **Manage tracked packages** - stop tracking (remove) any package,
     including archived packages. Remove an archived record here before
     adding the same tracking number again.
   - **Carrier API credentials** - all optional; fill in whichever native
     carriers you want, and/or any of the four fallback aggregators (tried
     in the order listed below, each assumed unreliable on its own - see
     "How it decides who to ask"). Get credentials from:
     - UPS: https://developer.ups.com (Track API, OAuth2 client
       credentials - you need a client ID and client secret)
     - FedEx: https://developer.fedex.com (Track API, OAuth2 client
       credentials)
     - DHL: https://developer.dhl.com (Unified Tracking API, a single API
       key - no OAuth)
     - USPS: https://developer.usps.com (Tracking API v3, OAuth2 client
       credentials - not the older, deprecated Web Tools XML API)
     - 17track (fallback 1 of 4): https://api.17track.net (register for a
       free account to get a "17token" API key)
     - AfterShip (fallback 2 of 4): https://www.aftership.com/api (free
       tier available)
     - TrackingMore (fallback 3 of 4): https://www.trackingmore.com/pricing.html
       (free tier available)
     - Ship24 (fallback 4 of 4): https://www.ship24.com/tracking-api (free
       tier available)
   - **Polling settings** - how often to poll (default 30 minutes) and how
     many days after delivery a package stops being tracked and its sensor
     is removed (default 5 days, 0 disables auto-archiving).

Each package becomes a `sensor.<name>` entity with state one of:
`info_received`, `in_transit`, `out_for_delivery`, `available_for_pickup`,
`delivered`, `delivery_exception`, `returned`, `needs_configuration`, or
`unknown`. Attributes include the tracking number, resolved carrier, which
backend answered, a human-readable status detail, estimated delivery, and
the most recent scan event's description/location/time. A single
`sensor.package_tracker_active_packages` counts everything not yet
delivered.

## Adding/removing packages without the UI

Two services do the same thing the options flow's "Add a package"/"Manage
tracked packages" steps do, for use from scripts, dashboards, or Developer
Tools:

```yaml
service: package_tracker.add_package
data:
  tracking_number: "1Z999AA10123456784"
  carrier: auto  # or ups / fedex / dhl / usps
  name: "Birthday gift"
```

```yaml
service: package_tracker.remove_package
data:
  tracking_number: "1Z999AA10123456784"
```

`package_tracker.refresh` polls every tracked package immediately instead of
waiting for the next scheduled update.

## Notifications

Every time a package's status changes, this integration fires a
`package_tracker_status_changed` event with `tracking_number`, `name`,
`carrier`, `previous_status`, `status`, and `status_detail`. Easiest way to
turn that into a push notification: import the included blueprint
(`blueprints/automation/package_tracker/notify_on_status_change.yaml`) via
Settings -> Automations -> Blueprints -> Import Blueprint, enter a
`notify` action name (e.g. `notify.mobile_app_your_phone` from the Home
Assistant Companion App), and pick which statuses should notify.

If you imported the blueprint before version 0.1.1, re-import it and replace
the old action-picker value with the notify action name.

Or write your own automation directly against the event:

```yaml
trigger:
  - trigger: event
    event_type: package_tracker_status_changed
    event_data:
      status: out_for_delivery
action:
  - action: notify.mobile_app_your_phone
    data:
      title: "{{ trigger.event.data.carrier | upper }} - Out for delivery"
      message: "{{ trigger.event.data.name }}: {{ trigger.event.data.status_detail }}"
```

(A plain `state` trigger on the package's sensor works too, since the state
itself is the status - the event just also carries `previous_status` and
`status_detail` in one payload.)

## Diagnostics

Settings -> Devices & Services -> Package Tracker -> Download diagnostics
gives a redacted snapshot (carrier credentials, tokens, package IDs, tracking
numbers, and friendly names stripped) - useful for filing an issue if a
carrier's API response shape has drifted from what's implemented here.

Tracking results are stored under Home Assistant's `.storage` directory and
removed when the integration is deleted. Removing or archiving a package
also removes its sensor registration and cached result; Recorder history
follows Home Assistant's own retention settings.

## Development

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
ruff check .
pytest
```

The development requirements pin Home Assistant 2026.10.0 and its matching
test harness. CI also runs the full suite against the minimum supported
Home Assistant 2025.1.4 on Python 3.13, and checks imports against the latest
Home Assistant release on Python 3.14. The test harness and Home Assistant
must be installed together to avoid silently replacing the version under test.

HACS validation runs in `.github/workflows/hacs.yml`. Keep the bundled
`custom_components/package_tracker/brand/icon.png`: HACS checks for it,
and Home Assistant 2026.3+ can display it directly. The editable source is
`brand/icon.svg`. To regenerate both PNG sizes with `rsvg-convert`:

```bash
rsvg-convert -w 256 -h 256 -o custom_components/package_tracker/brand/icon.png custom_components/package_tracker/brand/icon.svg
rsvg-convert -w 512 -h 512 -o custom_components/package_tracker/brand/icon@2x.png custom_components/package_tracker/brand/icon.svg
```
