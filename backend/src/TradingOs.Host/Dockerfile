# Build context is backend/ (docker-compose.yml) so ProjectReferences to
# sibling projects (Gateway, Persistence, Contracts) resolve normally.
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src
COPY . .
RUN dotnet publish src/TradingOs.Host/TradingOs.Host.csproj -c Release -o /app --no-self-contained

FROM mcr.microsoft.com/dotnet/aspnet:10.0 AS runtime
# Npgsql probes for GSSAPI at connection time regardless of the auth method
# actually in use (plain password here) — without this, the connection
# still works (falls back), but every attempt logs a scary-looking
# "cannot open shared object file" error that isn't one.
RUN apt-get update && apt-get install -y --no-install-recommends libgssapi-krb5-2 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /app .
# 5080: cockpit SignalR hub/HTTP. 9765: EA-05 execution agent TCP (ADR
# 0010). Both published to 127.0.0.1 only on the host (docker-compose.yml)
# — the container binds all interfaces internally (Cockpit__ListenUrl,
# Cockpit__AgentBindAny) only because a container's own loopback isn't
# reachable through Docker's port mapping, not because this is meant to be
# reachable from outside this machine.
EXPOSE 5080 9765
ENTRYPOINT ["dotnet", "TradingOs.Host.dll"]
