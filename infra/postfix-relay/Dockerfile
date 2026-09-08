# Thin rebuild of boky/postfix's 5.1.0 Alpine release, to close BACKLOG
# O15 (TTLI_Audit_Report_2026-09-02.md M3).
#
# Why this exists at all. The relay image was the one component kept out
# of ci.yml's blocking Trivy loop, because adding it meant rubber-stamping
# 72-ish unreviewed exceptions. A review on 2026-09-08 found that every
# single CRITICAL/HIGH finding in the pinned release -- 74 of them --
# already has a published Alpine fix. None of it is unpatchable upstream
# debt like the util-linux entries in .trivyignore; boky simply has not
# rebuilt this tag since 2026-01-04, and there is no newer *release* to
# move to (`edge-alpine` is rebuilt more often, but it is a mutable
# development tag, and its 24 findings are all fixable too -- less stale,
# not clean).
#
# So the honest fix is to rebuild rather than to except: one `apk upgrade`
# against current Alpine clears all 74, which is why postfix-relay is now
# in the blocking scan loop with no exceptions of its own.
#
# Deliberately a derived image, not a hand-rolled postfix. boky's
# /scripts/run.sh is what implements RELAYHOST, the SASL password maps and
# ALLOW_EMPTY_SENDER_DOMAINS that infra/docker-compose.single-vm.yml
# configures; reimplementing that is how outbound email breaks in ways
# nobody notices until a learner doesn't get a certificate. Only a package
# upgrade is applied here -- USER, ENTRYPOINT (/tini --), CMD, EXPOSE 587
# and the healthcheck are all inherited unchanged.
#
# Re-resolve the base deliberately (not on a schedule) with:
#   docker buildx imagetools inspect boky/postfix:5.1.0-alpine
FROM boky/postfix:5.1.0-alpine@sha256:6e761312e833947f77af755072c0e77b67d298d127595470a79e9454008dd594

# --no-cache so the package index isn't left in the layer. This is
# expected to be a no-op the day boky finally rebuilds the tag, which is
# fine -- it stays correct either way.
RUN apk upgrade --no-cache

# `apk upgrade` clears the OS packages but not the Python virtualenv at
# /sasl, which the image ships for XOAUTH2 relay auth (scripts/
# functions.sh's postfix_setup_xoauth2_pre_setup). This deployment
# authenticates with a plain SASL username/password against SMTP_RELAY_HOST
# and never takes that path, but an unused interpreter with known-vulnerable
# libraries is still surface sitting in the image, and all nine findings
# have published fixes -- so upgrade rather than except.
#
# msal is upgraded alongside them deliberately. cryptography's fix for
# CVE-2026-69247 lands in 50.0.0, and the pinned msal 1.34.0 caps it at
# <49 -- installing the fix alone leaves a dependency that still imports
# today but breaks on the first msal call touching a removed API. msal
# 1.38.0 widens the pin to <51, so both move together.
#
# `pip check` makes that permanent: it exits non-zero on any unsatisfied
# requirement, so the day a future upgrade re-opens this conflict the build
# fails here instead of shipping a quietly broken virtualenv. The import
# line additionally proves the packages load, which metadata alone doesn't.
RUN /sasl/bin/pip install --no-cache-dir --upgrade PyJWT cryptography urllib3 msal \
    && /sasl/bin/pip check \
    && /sasl/bin/python -c "import msal, jwt, cryptography, urllib3; print('xoauth2 helper imports OK')"
