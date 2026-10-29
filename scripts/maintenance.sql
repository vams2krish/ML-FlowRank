-- Run as a database administrator; runtime sessions cannot access other guests.
-- Daily retention cleanup. Expired sessions cascade to impressions and feedback.
DELETE FROM flowrank.sessions WHERE expires < extract(epoch from now());
DELETE FROM flowrank.rate_limits WHERE bucket < floor(extract(epoch from now())/60)-1440;
