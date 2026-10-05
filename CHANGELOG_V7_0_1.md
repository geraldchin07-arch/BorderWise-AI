# BorderWise AI v7.0.2

- Fixed slow initial dashboard loading caused by synchronous FX refreshes inside `/api/state`.
- Dashboard now renders immediately using the cached/fallback rate, then refreshes FX in a second request.
- Snapshot API no longer blocks on outbound FX requests unless explicitly requested.
- Added graceful frontend error handling for profile/state loading.
