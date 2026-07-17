"""Sanitized transcript fixtures for PR-049 (POLYGLOT) driver testing.

Every transcript here is a sanitized rendition of realistic platform output:
lab hostnames, documentation addresses (192.0.2.0/24, 198.51.100.0/24,
203.0.113.0/24 and RFC1918), invented serials. No credentials, no customer
data. Tests run the REAL parsers and normalization against these — but a
transcript-tested driver is not a live-tested driver, and the maturity
labels say so.
"""
