#include "../src/ContextCache.h"
#include <catch2/catch.hpp>

TEST_CASE("Context history keeps its capture age through transfer and logout", "[context]")
{
    CataContext::Cache cache({42}, 1000);
    cache.Login(42, 10, 100);
    CataContext::Sample row;
    row.Guid = 42; row.Generation = *cache.Due(42, 10);
    row.State = "online"; row.HasPlayer = true; row.SampledMs = 20;
    row.History.Available = true; row.History.LastSequence = 7;
    row.HistoryGeneration = row.Generation; row.HistorySampledMs = 20; row.HistoryWallMs = 110;
    REQUIRE(cache.Publish(row));
    CataContext::Sample transfer;
    transfer.Guid = 42; transfer.Generation = row.Generation;
    transfer.State = "transferring"; transfer.SampledMs = 2000;
    REQUIRE(cache.Publish(transfer));
    REQUIRE(cache.Read().front().History.LastSequence == 7);
    REQUIRE(cache.Read().front().HistorySampledMs == 20);
    cache.Logout(42, 3000, 3090);
    auto archived = cache.Read().front();
    REQUIRE_FALSE(archived.HasPlayer);
    REQUIRE(archived.History.Available);
    REQUIRE(archived.HistoryGeneration == row.Generation);
    REQUIRE(archived.HistoryWallMs == 110);
    cache.Login(42, 4000, 4090);
    REQUIRE_FALSE(cache.Read().front().History.Available);
    REQUIRE(cache.Read().front().History.LastSequence == 0);
}

TEST_CASE("Context API drops samples from a prior login generation", "[context]")
{
    CataContext::Cache cache({42}, 1000);
    REQUIRE_FALSE(cache.Due(42, 0));
    cache.Login(42, 10, 100);
    auto generation = cache.Due(42, 10);
    REQUIRE(generation);
    CataContext::Sample pending;
    pending.Guid = 42; pending.Generation = *generation; pending.SampledMs = 20;
    pending.HasPlayer = true; pending.State = "online";
    cache.Logout(42, 30, 130);
    cache.Login(42, 40, 140);
    REQUIRE_FALSE(cache.Publish(pending));
    auto row = cache.Read().front();
    REQUIRE(row.State == "awaiting_sample");
    REQUIRE_FALSE(row.HasPlayer);
}

TEST_CASE("Context API bounds scope cadence and clears offline state", "[context]")
{
    CataContext::Cache cache({42}, 1000);
    cache.Login(43, 0, 0);
    REQUIRE(cache.Read().size() == 1);
    cache.Login(42, 10, 100);
    CataContext::Sample row;
    row.Guid = 42; row.Generation = *cache.Due(42, 10);
    row.State = "online"; row.HasPlayer = true; row.SampledMs = 10;
    REQUIRE(cache.Publish(row));
    REQUIRE_FALSE(cache.Due(42, 1009));
    REQUIRE(cache.Due(42, 1010));
    cache.Logout(42, 1020, 1120);
    REQUIRE(cache.Read().front().State == "offline");
    REQUIRE_FALSE(cache.Read().front().HasPlayer);
    REQUIRE_FALSE(cache.Due(42, 10000));
    REQUIRE_FALSE(cache.Publish(row));
}
