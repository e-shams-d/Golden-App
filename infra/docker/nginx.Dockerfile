FROM nginx:1.30.4-alpine3.24

COPY infra/nginx/nginx.conf /etc/nginx/nginx.conf
COPY infra/nginx/conf.d /etc/nginx/conf.d

RUN rm -f /etc/nginx/conf.d/default.conf

USER nginx
EXPOSE 8080
STOPSIGNAL SIGQUIT
ENTRYPOINT []
CMD ["nginx", "-g", "daemon off;"]
