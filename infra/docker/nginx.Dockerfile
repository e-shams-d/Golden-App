FROM nginx:1.30.4-alpine3.24

# **Take the distribution's published fixes at build time.** Gate 6 fails on findings that have a
# fix available, and this base lags its own repository: measured on 2026-08-27, five installed
# packages were behind — `libcrypto3` and `libssl3` at 3.5.7-r0 against 3.5.8-r0, `libexpat` at
# 2.8.2-r0 against 2.8.3-r0, and `apk-tools`/`libapk` at 3.0.6-r0 against 3.0.7-r0. An OpenSSL
# advisory with a published fix is exactly what that gate exists to refuse to ship.
#
# **A tag bump does not help, and that was checked rather than assumed.** `nginx:alpine` — currently
# 1.31.4 — has the identical 71 packages at the identical versions; the *only* difference from this
# pinned tag is the nginx package itself. So the fix cannot come from following the tag; it has to
# come from asking apk for what the repository already has.
#
# The pinned base stays. It fixes nginx's own version and the alpine release, which is what makes an
# image reviewable; this line keeps the packages inside it patched. Gate 8 records the resulting
# digest, so what shipped is still identified exactly even though the package set is no longer a
# function of the tag alone.
#
# `--no-cache` leaves no index behind. `apk upgrade` rather than `apk add` of named versions: a pinned
# `libssl3=3.5.8-r0` fails the build the day alpine publishes 3.5.9-r0 and drops the older one, which
# turns a security update into an outage.
RUN apk upgrade --no-cache

COPY infra/nginx/nginx.conf /etc/nginx/nginx.conf
COPY infra/nginx/conf.d /etc/nginx/conf.d

RUN rm -f /etc/nginx/conf.d/default.conf

USER nginx
EXPOSE 8080
STOPSIGNAL SIGQUIT
ENTRYPOINT []
CMD ["nginx", "-g", "daemon off;"]
