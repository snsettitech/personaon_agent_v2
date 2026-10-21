# PersonaOn AI — Frontend Dockerfile
# Runtime: Next.js 16 standalone output
# Target: GCP Cloud Run (port 3000)
# Prerequisite: next.config.ts must have output: 'standalone' (already set)

FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# Build-time env vars injected via --build-arg in GitHub Actions workflow
ARG NEXT_PUBLIC_SUPABASE_URL
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY
ARG NEXT_PUBLIC_BACKEND_URL
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_FRONTEND_URL
ARG NEXT_PUBLIC_DEMO_TWIN_ID
ARG NEXT_PUBLIC_DEMO_SHARE_TOKEN
ARG NEXT_PUBLIC_POSTHOG_KEY
ARG NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY
# Persona layout themes runtime flag (default off -> Classic-only). Pass
# --build-arg NEXT_PUBLIC_PERSONA_THEMES="true" in the deploy workflow to enable.
ARG NEXT_PUBLIC_PERSONA_THEMES
# Assistant Home v1 flag (default off -> /dashboard redirects to meetings). Pass
# --build-arg NEXT_PUBLIC_FLAG_ASSISTANT_HOME_V1="true" to surface the persona-
# assistant Home. See plans/home-v1-assistant.md (A1/E1).
ARG NEXT_PUBLIC_FLAG_ASSISTANT_HOME_V1
ENV NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL
ENV NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY
ENV NEXT_PUBLIC_BACKEND_URL=$NEXT_PUBLIC_BACKEND_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_FRONTEND_URL=$NEXT_PUBLIC_FRONTEND_URL
ENV NEXT_PUBLIC_DEMO_TWIN_ID=$NEXT_PUBLIC_DEMO_TWIN_ID
ENV NEXT_PUBLIC_DEMO_SHARE_TOKEN=$NEXT_PUBLIC_DEMO_SHARE_TOKEN
ENV NEXT_PUBLIC_POSTHOG_KEY=$NEXT_PUBLIC_POSTHOG_KEY
ENV NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=$NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY
ENV NEXT_PUBLIC_PERSONA_THEMES=$NEXT_PUBLIC_PERSONA_THEMES
ENV NEXT_PUBLIC_FLAG_ASSISTANT_HOME_V1=$NEXT_PUBLIC_FLAG_ASSISTANT_HOME_V1
RUN npm run build

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
