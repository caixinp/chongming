# ================================================
# Builder stage: build Vue frontend
# ================================================
FROM node:22-alpine AS builder

WORKDIR /build

# Step 1: Copy package metadata for dependency caching
COPY front/chongming_front/package.json front/chongming_front/package-lock.json ./
RUN npm ci

# Step 2: Copy source code and build
COPY front/chongming_front/ .
RUN npm run build-only

# ================================================
# Production stage: nginx serving static files
# ================================================
FROM nginx:alpine

# Copy built static files
COPY --from=builder /build/dist /usr/share/nginx/html

# Copy nginx config with frontend + API proxy
COPY docker-env/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD wget -qO- http://localhost:80/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
