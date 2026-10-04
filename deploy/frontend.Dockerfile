# The DocuFlow web app as a plain OCI image, built once and served by vinext.
#
# The browser calls the API at NEXT_PUBLIC_API_URL, which is fixed when the
# image is built: build one image per environment, or put both services behind
# one origin and pass that origin.
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
RUN npm run build

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production PORT=3000
COPY --from=build /app/package.json /app/package-lock.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
USER node
EXPOSE 3000
CMD ["sh", "-c", "exec npx vinext start --port ${PORT} --hostname 0.0.0.0"]
