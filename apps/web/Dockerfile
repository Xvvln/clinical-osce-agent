FROM node:20-bookworm-slim

ARG CLINICAL_OSCE_WEB_API_URL=http://api:8000
ARG NEXT_PUBLIC_CLINICAL_OSCE_DEPLOYMENT_MODE=local-demo

ENV NEXT_TELEMETRY_DISABLED=1 \
    CLINICAL_OSCE_WEB_API_URL=${CLINICAL_OSCE_WEB_API_URL} \
    NEXT_PUBLIC_CLINICAL_OSCE_DEPLOYMENT_MODE=${NEXT_PUBLIC_CLINICAL_OSCE_DEPLOYMENT_MODE}

WORKDIR /app/apps/web

RUN corepack enable \
    && corepack prepare pnpm@10.5.1 --activate

COPY apps/web/package.json apps/web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY apps/web ./
RUN pnpm build

ENV NODE_ENV=production
EXPOSE 3000

CMD ["pnpm", "start", "--hostname", "0.0.0.0", "--port", "3000"]
