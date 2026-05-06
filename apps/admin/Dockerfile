FROM node:20-bookworm-slim

ARG CLINICAL_OSCE_ADMIN_API_URL=http://api:8000

ENV NEXT_TELEMETRY_DISABLED=1 \
    CLINICAL_OSCE_ADMIN_API_URL=${CLINICAL_OSCE_ADMIN_API_URL}

WORKDIR /app/apps/admin

RUN corepack enable \
    && corepack prepare pnpm@10.5.1 --activate

COPY apps/admin/package.json apps/admin/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY apps/admin ./
RUN pnpm build

ENV NODE_ENV=production
EXPOSE 3000

CMD ["pnpm", "start", "--hostname", "0.0.0.0", "--port", "3000"]
