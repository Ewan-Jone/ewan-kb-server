FROM python:3.12-slim

RUN pip install --no-cache-dir ewan-kb-server>=0.1.2

ENV EWANKB_SERVER_CONFIG=/config/config.json
ENV EWANKB_SERVER_KBS=/config/kbs.json

EXPOSE 3000

CMD ["ewankb-server"]