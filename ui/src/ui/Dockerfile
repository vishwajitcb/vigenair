# ViGenAiR Frontend Dockerfile
# Angular 17 with Nginx

# Build stage
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files (from ui subdirectory)
COPY ui/package*.json ./

# Install dependencies
RUN npm ci

# Copy all source code (including shared utils from parent)
COPY . .

# Change to ui directory and build
WORKDIR /app/ui
RUN npm run build -- --configuration=production

# Production stage
FROM nginx:alpine

# Copy nginx configuration
COPY ui/nginx.conf /etc/nginx/nginx.conf

# Copy built Angular app
COPY --from=builder /app/ui/dist/ui/browser /usr/share/nginx/html

# Create non-root user
RUN adduser -D -g '' nginxuser && \
    chown -R nginxuser:nginxuser /usr/share/nginx/html && \
    chown -R nginxuser:nginxuser /var/cache/nginx && \
    chown -R nginxuser:nginxuser /var/log/nginx && \
    touch /var/run/nginx.pid && \
    chown -R nginxuser:nginxuser /var/run/nginx.pid

# Expose ports
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:80/ || exit 1

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
