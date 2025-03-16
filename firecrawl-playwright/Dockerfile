FROM ubuntu:latest as builder
WORKDIR /workspace
RUN apt-get update && apt-get install -y git
RUN git clone https://github.com/mendableai/firecrawl.git

FROM node:18-slim

WORKDIR /usr/src/app
COPY --from=builder /workspace/firecrawl/apps/playwright-service-ts/package*.json ./
RUN npm install

COPY --from=builder /workspace/firecrawl/apps/playwright-service-ts/ .

# Install Playwright dependencies
RUN npx playwright install --with-deps

RUN npm run build

ARG PORT
ENV PORT=${PORT}

EXPOSE ${PORT}

CMD [ "npm", "start" ]