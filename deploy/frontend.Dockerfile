FROM node:22-alpine AS build

WORKDIR /app
COPY backend/shared/schemas ./backend/shared/schemas
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci

COPY frontend ./frontend
RUN cd frontend && npm run build

FROM nginx:1.27-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/dist/dancing-with-the-sars/browser /usr/share/nginx/html
EXPOSE 80
