/* GPL v2 or later. Read-only diagnostic module; no native game object ownership. */
#ifndef CATA_CONTEXT_CACHE_H
#define CATA_CONTEXT_CACHE_H
#include "PlayerbotContextState.h"
#include <chrono>
#include <map>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace CataContext
{
struct PhaseInfo
{
    uint32 Flags = 0, Total = 0;
    uint64 PersonalGuid = 0;
    std::vector<std::pair<uint32, uint32>> Entries;
};
struct UnitRelation
{
    uint64 Guid = 0;
    bool Available = false, Alive = false, Combat = false;
    bool CanSeePhase = false, ReverseCanSeePhase = false, FrontHalf = false, MeleeRange = false;
    std::string Name;
    uint32 Map = 0, Instance = 0;
    float Distance = 0, RelativeAngle = 0, NativeMeleeRange = 0;
    PhaseInfo Phase;
};
struct PeerPhase
{
    uint64 Guid = 0;
    bool Available = false, CanSeePhase = false, ReverseCanSeePhase = false;
};
struct Sample
{
    uint64 Guid = 0, Generation = 0, SampledMs = 0, WallMs = 0;
    std::string State = "unobserved", Name;
    bool HasPlayer = false, IsBot = false, Alive = false, Combat = false;
    uint64 Group = 0, Target = 0, Controller = 0, FollowTarget = 0;
    uint32 Map = 0, Instance = 0, Health = 0, MaxHealth = 0;
    uint32 Power = 0, MaxPower = 0, PowerType = 0, RoleMask = 0;
    float X = 0, Y = 0, Z = 0, Orientation = 0;
    bool AttackRequested = false;
    bool Movement = false, Falling = false;
    uint32 MovementFlags = 0;
    float RunSpeed = 0, SwimSpeed = 0, FlightSpeed = 0;
    bool Diagnostics = false;
    PhaseInfo Phase;
    UnitRelation SelectedUnit, AttackVictim;
    std::vector<PeerPhase> Peers;
    PlayerbotContextState Bot;
    PlayerbotActionHistory History;
    uint64 HistoryGeneration = 0, HistorySampledMs = 0, HistoryWallMs = 0;
};

// Login/logout establish generations. A sample captured before logout or a
// replacement session cannot publish into the next generation.
class Cache
{
public:
    Cache(std::vector<uint64> const& guids, uint32 interval) : _interval(interval)
    {
        for (uint64 guid : guids) { Sample row; row.Guid = guid; _rows.emplace(guid, std::move(row)); }
    }
    void Login(uint64 guid, uint64 now, uint64 wall)
    {
        std::lock_guard<std::mutex> guard(_mutex);
        auto found = _rows.find(guid);
        if (found == _rows.end()) return;
        uint64 generation = found->second.Generation + 1;
        found->second = Sample{};
        found->second.Guid = guid; found->second.Generation = generation;
        found->second.State = "awaiting_sample";
        found->second.SampledMs = now; found->second.WallMs = wall;
    }
    void Logout(uint64 guid, uint64 now, uint64 wall)
    {
        std::lock_guard<std::mutex> guard(_mutex);
        auto found = _rows.find(guid);
        if (found == _rows.end()) return;
        uint64 generation = found->second.Generation + 1;
        auto history = std::move(found->second.History);
        uint64 historyGeneration = found->second.HistoryGeneration;
        uint64 historySampled = found->second.HistorySampledMs, historyWall = found->second.HistoryWallMs;
        found->second = Sample{};
        found->second.Guid = guid; found->second.Generation = generation;
        found->second.State = "offline";
        found->second.SampledMs = now; found->second.WallMs = wall;
        found->second.History = std::move(history); found->second.HistoryGeneration = historyGeneration;
        found->second.HistorySampledMs = historySampled; found->second.HistoryWallMs = historyWall;
    }
    std::optional<uint64> Due(uint64 guid, uint64 now) const
    {
        std::lock_guard<std::mutex> guard(_mutex);
        auto found = _rows.find(guid);
        if (found == _rows.end()) return {};
        auto const& row = found->second;
        if (row.State == "offline" || row.State == "unobserved") return {};
        if (row.State != "awaiting_sample" && now - row.SampledMs < _interval) return {};
        return row.Generation;
    }
    bool Publish(Sample sample)
    {
        std::lock_guard<std::mutex> guard(_mutex);
        auto found = _rows.find(sample.Guid);
        if (found == _rows.end() || found->second.Generation != sample.Generation ||
            found->second.State == "offline" || sample.SampledMs < found->second.SampledMs)
            return false;
        // Transfer callbacks cannot read the engine. Keep the previous historical
        // copy with its original age rather than refreshing or discarding it.
        if (sample.State == "transferring" && !sample.HasPlayer)
        {
            sample.History = found->second.History;
            sample.HistoryGeneration = found->second.HistoryGeneration;
            sample.HistorySampledMs = found->second.HistorySampledMs;
            sample.HistoryWallMs = found->second.HistoryWallMs;
        }
        found->second = std::move(sample);
        return true;
    }
    std::vector<Sample> Read() const
    {
        std::lock_guard<std::mutex> guard(_mutex);
        std::vector<Sample> result;
        for (auto const& [guid, row] : _rows) { (void)guid; result.push_back(row); }
        return result;
    }
private:
    uint32 _interval;
    mutable std::mutex _mutex;
    std::map<uint64, Sample> _rows;
};
}
#endif
