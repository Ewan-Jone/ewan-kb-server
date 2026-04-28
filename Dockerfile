FROM python:3.12-slim

COPY dist/ewan_kb_server-0.1.2-py3-none-any.whl /tmp/

RUN unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy && \
    pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    /tmp/ewan_kb_server-0.1.2-py3-none-any.whl && \
    rm /tmp/ewan_kb_server-0.1.2-py3-none-any.whl

ENV EWANKB_SERVER_CONFIG=/config/config.json
ENV EWANKB_SERVER_KBS=/config/kbs.json

EXPOSE 3000

CMD ["ewankb-server"]