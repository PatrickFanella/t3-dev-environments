FROM ckulka/baikal:0.10.1-nginx@sha256:434bdd162247cc6aa6f878c9b4dce6216e39e79526b980453b13812d5f8ebf4b AS application
FROM php:8.3.36-apache-bookworm@sha256:cbd3b3d9011668443d54ab40ec31db56c73d91b4c8198935d639aa80d2d815c1

# Preserve Baikal's application version, data paths and original UID/GID.
RUN groupadd --gid 101 baikal \
    && useradd --uid 101 --gid 101 --no-create-home baikal \
    && a2enmod rewrite headers \
    && cp /usr/local/etc/php/php.ini-production /usr/local/etc/php/php.ini
COPY --from=application --chown=101:101 /var/www/baikal /var/www/baikal
COPY apache-baikal.conf /etc/apache2/sites-available/000-default.conf
ENV APACHE_RUN_USER=baikal APACHE_RUN_GROUP=baikal
VOLUME ["/var/www/baikal/Specific", "/var/www/baikal/config"]
WORKDIR /var/www/baikal
