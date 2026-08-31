FROM node:20-alpine AS build

WORKDIR /app
COPY apps/web/package*.json ./
RUN npm ci
COPY apps/web ./
ARG NEXT_PUBLIC_CTF_API_URL=http://localhost:8080/api/v1
ARG NEXT_PUBLIC_USE_MOCKS=false
ENV NEXT_PUBLIC_CTF_API_URL=$NEXT_PUBLIC_CTF_API_URL \
    NEXT_PUBLIC_USE_MOCKS=$NEXT_PUBLIC_USE_MOCKS
RUN npm run build

FROM node:20-alpine AS runtime
ENV NODE_ENV=production
WORKDIR /app
COPY --from=build /app ./
EXPOSE 3000
CMD ["npm", "start", "--", "-p", "3000"]
