/* GPL v2 or later. See the matching TrinityCore AUTHORS file. */
#include "ContextCache.h"
#include "ContextBuild.h"
#include "Config.h"
#include "GitRevision.h"
#include "Group.h"
#include "Log.h"
#include "ObjectGuid.h"
#include "ObjectAccessor.h"
#include "Map.h"
#include "Player.h"
#include "Realm.h"
#include "ScriptMgr.h"
#include "WorldSession.h"
#include "World.h"
#include <rapidjson/stringbuffer.h>
#include <rapidjson/writer.h>
#include <atomic>
#include <algorithm>
#include <charconv>
#include <condition_variable>
#include <filesystem>
#include <fstream>
#include <random>
#include <thread>
#ifdef _WIN32
#include <windows.h>
#endif

namespace CataContext
{
using Clock = std::chrono::steady_clock;
uint64 WallMs()
{
    return uint64(std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count());
}

PhaseInfo CopyPhase(WorldObject const& object)
{
    PhaseInfo result;
    auto const& phase = object.GetPhaseShift();
    result.Flags = phase.GetFlags().AsUnderlyingType();
    result.PersonalGuid = phase.GetPersonalGuid().GetRawValue();
    result.Total = uint32(phase.GetPhases().size());
    for (auto const& entry : phase.GetPhases())
    {
        if (result.Entries.size() == 32) break;
        result.Entries.emplace_back(entry.Id, entry.Flags.AsUnderlyingType());
    }
    return result;
}

UnitRelation CopyRelation(Player const& player, uint64 guid, Unit const* unit)
{
    UnitRelation result; result.Guid = guid;
    if (!unit || !unit->IsInWorld() || !player.IsInMap(unit)) return result;
    constexpr float Pi = 3.14159265358979323846f;
    result.Available = true; result.Name = unit->GetName();
    result.Alive = unit->IsAlive(); result.Combat = unit->IsInCombat();
    result.Map = unit->GetMapId(); result.Instance = unit->GetInstanceId();
    result.Phase = CopyPhase(*unit);
    result.CanSeePhase = player.IsInPhase(unit);
    result.ReverseCanSeePhase = unit->IsInPhase(&player);
    result.Distance = player.GetExactDist(unit); // centre-to-centre, not combat-reach-adjusted
    result.RelativeAngle = Position::NormalizeOrientation(player.GetRelativeAngle(unit));
    if (result.RelativeAngle > Pi) result.RelativeAngle -= 2 * Pi;
    result.FrontHalf = player.HasInArc(Pi, unit);
    result.NativeMeleeRange = player.GetMeleeRange(unit);
    result.MeleeRange = player.IsWithinMeleeRange(unit); // includes native map/phase checks
    return result;
}

class Exporter
{
public:
    Exporter(std::vector<uint64> guids, uint32 interval, std::string file, bool diagnostics, bool history, bool movement)
        : _cache(guids, interval), _interval(interval), _file(std::move(file)),
          _origin(Clock::now()), _startedWall(WallMs()), _realmId(realm.Id.Realm),
          _guids(std::move(guids)), _diagnostics(diagnostics), _history(history), _movement(movement)
    {
        std::random_device random;
        _boot = std::to_string(_startedWall) + "-" + std::to_string(random());
    }
    ~Exporter() { Stop(); }
    uint64 Now() const { return uint64(std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - _origin).count()); }
    void Start() { _enabled.store(true); _writer = std::thread([this] { Run(); }); }
    void Stop()
    {
        _enabled.store(false);
        { std::lock_guard<std::mutex> guard(_waitMutex); _stop = true; }
        _wake.notify_all();
        if (_writer.joinable()) _writer.join();
    }
    bool Enabled() const { return _enabled.load(); }
    Cache& Rows() { return _cache; }
    bool Diagnostics() const { return _diagnostics; }
    bool History() const { return _history; }
    bool Movement() const { return _movement; }
    std::vector<uint64> const& Guids() const { return _guids; }

private:
    void Write(bool stopped)
    {
        auto rows = _cache.Read(); // All later work uses only copied data.
        rapidjson::StringBuffer buffer;
        rapidjson::Writer<rapidjson::StringBuffer> json(buffer);
        auto text = [&](char const* key, std::string const& value) { json.Key(key); json.String(value.c_str(), uint32(value.size())); };
        auto number = [&](char const* key, uint64 value) { json.Key(key); json.Uint64(value); };
        auto boolean = [&](char const* key, bool value) { json.Key(key); json.Bool(value); };
        auto guid = [&](char const* key, uint64 value) { json.Key(key); if (value) json.String(std::to_string(value).c_str()); else json.Null(); };
        auto strings = [&](char const* key, std::vector<std::string> const& values) {
            json.Key(key); json.StartArray(); for (auto const& value : values) json.String(value.c_str()); json.EndArray();
        };
        auto phase = [&](char const* key, PhaseInfo const& value) {
            json.Key(key); json.StartObject(); number("flags", value.Flags);
            guid("personal_guid", value.PersonalGuid); number("total_entries", value.Total);
            boolean("complete", value.Total == value.Entries.size());
            json.Key("entries"); json.StartArray();
            for (auto const& [id, flags] : value.Entries)
            { json.StartObject(); number("id", id); number("flags", flags); json.EndObject(); }
            json.EndArray(); json.EndObject();
        };
        auto relation = [&](char const* key, UnitRelation const& value) {
            json.Key(key);
            if (!value.Guid) { json.Null(); return; }
            json.StartObject(); guid("guid", value.Guid); boolean("details_available", value.Available);
            if (value.Available)
            {
                text("name", value.Name); boolean("alive", value.Alive); boolean("in_combat", value.Combat);
                number("map_id", value.Map); number("instance_id", value.Instance); phase("phase", value.Phase);
                boolean("player_can_see_unit_phase", value.CanSeePhase);
                boolean("unit_can_see_player_phase", value.ReverseCanSeePhase);
                boolean("in_front_half", value.FrontHalf); boolean("within_native_melee_range", value.MeleeRange);
                json.Key("centre_distance_yards"); json.Double(value.Distance);
                json.Key("relative_angle_rad"); json.Double(value.RelativeAngle);
                json.Key("native_melee_range_yards"); json.Double(value.NativeMeleeRange);
            }
            json.EndObject();
        };
        json.StartObject(); number("schema_version", 1); text("source", "server");
        json.Key("server"); json.StartObject(); text("boot_id", _boot);
        text("status", stopped ? "stopped" : "running"); number("realm_id", _realmId);
        text("expansion", "cata"); text("core", "TrinityCore"); number("client_build", 15595); text("core_revision", GitRevision::GetHash());
        text("playerbots_revision", CONTEXT_PLAYERBOTS_REVISION);
        text("adapter_version", "0.4.0"); number("started_at_ms", _startedWall);
        number("exported_at_ms", WallMs()); number("uptime_ms", Now());
        number("sequence", ++_sequence); number("sample_interval_ms", _interval); json.EndObject();
        json.Key("scope"); json.StartObject(); boolean("roster_complete", false);
        json.Key("characters"); json.StartArray();
        for (auto const& row : rows) json.String(std::to_string(row.Guid).c_str());
        json.EndArray(); json.EndObject();
        json.Key("capabilities"); json.StartObject();
        std::vector<std::string> methods{"context.get_capabilities", "game.get_party", "playerbots.get_bot_state"};
        if (_history) methods.push_back("playerbots.get_action_history");
        strings("query_methods", methods);
        boolean("control", false); boolean("history", _history); boolean("movement", _movement);
        strings("diagnostic_fields", _diagnostics ? std::vector<std::string>{"native_phase", "selected_unit_geometry", "attack_victim_geometry", "configured_peer_phase_checks"} : std::vector<std::string>{});
        json.EndObject();
        json.Key("entities"); json.StartArray();
        for (auto const& row : rows)
        {
            json.StartObject(); guid("guid", row.Guid); number("session_generation", row.Generation);
            text("state", row.State); number("sampled_ms", row.SampledMs); number("sampled_at_ms", row.WallMs);
            if (_history)
            {
                auto const& history = row.History;
                json.Key("action_history"); json.StartObject(); boolean("available", history.Available);
                number("session_generation", row.HistoryGeneration); number("captured_ms", row.HistorySampledMs);
                number("captured_at_ms", row.HistoryWallMs); number("epoch", history.Epoch);
                number("last_sequence", history.LastSequence); number("overwritten", history.Overwritten);
                number("expired", history.Expired); number("suppressed", history.Suppressed);
                number("retention_ms", 60000); number("capacity", 64);
                json.Key("events"); json.StartArray();
                for (auto const& event : history.Events)
                {
                    json.StartObject(); number("sequence", event.Sequence); number("first_sequence", event.FirstSequence);
                    number("first_age_ms", event.FirstAgeMs); number("last_age_ms", event.LastAgeMs); number("repeats", event.Repeats);
                    text("engine", event.Engine); text("action", event.Action); text("kind", event.Kind); text("reason", event.Reason);
                    boolean("execute_called", event.ExecuteCalled);
                    json.Key("action_return"); if (event.ActionReturn) json.Bool(*event.ActionReturn); else json.Null();
                    json.Key("engine_result"); if (event.EngineResult) json.Bool(*event.EngineResult); else json.Null();
                    json.EndObject();
                }
                json.EndArray(); json.EndObject();
            }
            json.Key("player");
            if (!row.HasPlayer) json.Null();
            else
            {
                json.StartObject(); text("name", row.Name); text("origin", row.IsBot ? "server" : "client");
                guid("group_guid", row.Group); guid("selected_target_guid", row.Target);
                boolean("alive", row.Alive); boolean("in_combat", row.Combat);
                number("map_id", row.Map); number("instance_id", row.Instance);
                json.Key("health"); json.StartObject(); number("current", row.Health); number("max", row.MaxHealth); json.EndObject();
                json.Key("power"); json.StartObject(); number("type", row.PowerType); number("current", row.Power); number("max", row.MaxPower); json.EndObject();
                json.Key("position"); json.StartObject();
                json.Key("x"); json.Double(row.X); json.Key("y"); json.Double(row.Y);
                json.Key("z"); json.Double(row.Z); json.Key("orientation"); json.Double(row.Orientation); json.EndObject();
                if (row.Movement)
                {
                    json.Key("movement"); json.StartObject();
                    text("kind", "native_movement_v1"); text("source", "server_native_state");
                    number("flags_raw", row.MovementFlags); boolean("falling", row.Falling);
                    json.Key("run_speed"); json.Double(row.RunSpeed);
                    json.Key("swim_speed"); json.Double(row.SwimSpeed);
                    json.Key("flight_speed"); json.Double(row.FlightSpeed); json.EndObject();
                }
                if (row.Diagnostics)
                {
                    json.Key("diagnostics"); json.StartObject(); text("kind", "native_phase_engagement_v1");
                    phase("phase", row.Phase); relation("selected_unit", row.SelectedUnit);
                    relation("attack_victim", row.AttackVictim);
                    json.Key("configured_peer_phases"); json.StartArray();
                    for (auto const& peer : row.Peers)
                    {
                        json.StartObject(); guid("guid", peer.Guid); boolean("details_available", peer.Available);
                        if (peer.Available)
                        { boolean("player_can_see_peer_phase", peer.CanSeePhase); boolean("peer_can_see_player_phase", peer.ReverseCanSeePhase); }
                        json.EndObject();
                    }
                    json.EndArray(); json.EndObject();
                }
                json.EndObject();
            }
            json.Key("bot");
            if (!row.HasPlayer || !row.IsBot) json.Null();
            else
            {
                json.StartObject(); boolean("available", row.Bot.Available);
                guid("controller_guid", row.Controller); guid("follow_target_guid", row.FollowTarget);
                boolean("attack_requested", row.AttackRequested); number("role_mask", row.RoleMask);
                if (row.Bot.Available)
                {
                    boolean("staying", row.Bot.Staying); text("engine_state", row.Bot.EngineState);
                    json.Key("last_executed_action");
                    if (row.Bot.LastExecutedAction.empty()) json.Null(); else json.String(row.Bot.LastExecutedAction.c_str());
                    number("queued_count", row.Bot.QueuedCount);
                    strings("combat_strategies", row.Bot.CombatStrategies);
                    strings("noncombat_strategies", row.Bot.NonCombatStrategies);
                }
                json.EndObject();
            }
            json.EndObject();
        }
        json.EndArray(); json.EndObject();
        auto temporary = _file; temporary += ".tmp";
        if (!_file.parent_path().empty()) std::filesystem::create_directories(_file.parent_path());
        { std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
          stream.write(buffer.GetString(), std::streamsize(buffer.GetSize())); stream.flush();
          if (!stream) throw std::runtime_error("snapshot write failed"); }
#ifdef _WIN32
        // ReplaceFile permits share-delete readers to retain the prior file.
        // MoveFileEx is only used for the first publication, with no target.
        if (!ReplaceFileW(_file.c_str(), temporary.c_str(), nullptr, 0, nullptr, nullptr))
        {
            DWORD error = GetLastError();
            if (error != ERROR_FILE_NOT_FOUND || !MoveFileExW(temporary.c_str(), _file.c_str(), MOVEFILE_WRITE_THROUGH))
                throw std::runtime_error("snapshot replacement failed");
        }
#else
        std::filesystem::rename(temporary, _file);
#endif
    }
    void Run()
    {
        for (;;)
        {
            bool stopped;
            { std::lock_guard<std::mutex> guard(_waitMutex); stopped = _stop; }
            try { Write(stopped); }
            catch (std::exception const& error)
            {
                // File failures never abort native gameplay. Throttle repeated errors.
                if (++_errors == 1 || _errors % 60 == 0)
                    TC_LOG_ERROR("module.context", "Context API snapshot export failed: %s", error.what());
            }
            if (stopped) return;
            std::unique_lock<std::mutex> lock(_waitMutex);
            _wake.wait_for(lock, std::chrono::milliseconds(_interval), [this] { return _stop; });
        }
    }
    Cache _cache;
    uint32 _interval, _realmId;
    std::filesystem::path _file;
    Clock::time_point _origin;
    uint64 _startedWall, _sequence = 0, _errors = 0;
    std::string _boot;
    std::vector<uint64> const _guids;
    bool const _diagnostics;
    bool const _history;
    bool const _movement;
    std::atomic<bool> _enabled {false};
    std::thread _writer;
    std::mutex _waitMutex;
    std::condition_variable _wake;
    bool _stop = false;
};

// Created before logins, retained until process exit. No runtime reconfiguration
// or destruction can race a map reader.
std::unique_ptr<Exporter> Service;
class ContextWorld final : public WorldScript
{
public:
    ContextWorld() : WorldScript("ContextAPIWorld") { }
    void OnStartup() override
    {
        if (!sConfigMgr->GetBoolDefault("ContextAPI.Enabled", false)) return;
        std::vector<uint64> guids;
        std::string input = sConfigMgr->GetStringDefault("ContextAPI.Characters", "");
        size_t offset = 0;
        while (offset < input.size())
        {
            size_t end = input.find(',', offset);
            if (end == std::string::npos) end = input.size();
            uint32 counter = 0;
            auto parsed = std::from_chars(input.data() + offset, input.data() + end, counter);
            if (!counter || parsed.ec != std::errc{} || parsed.ptr != input.data() + end ||
                std::find(guids.begin(), guids.end(), uint64(counter)) != guids.end() || guids.size() >= 8)
            { guids.clear(); break; }
            guids.push_back(ObjectGuid::Create<HighGuid::Player>(counter).GetRawValue());
            offset = end + 1;
            if (end < input.size() && offset == input.size()) { guids.clear(); break; }
        }
        int32 interval = sConfigMgr->GetIntDefault("ContextAPI.IntervalMs", 1000);
        std::string file = sConfigMgr->GetStringDefault("ContextAPI.SnapshotFile", "context-api/snapshot.json");
        if (guids.empty() || interval < 250 || interval > 10000 || file.empty())
        { TC_LOG_ERROR("module.context", "Context API disabled: invalid characters, interval, or snapshot path."); return; }
        try
        {
            Service = std::make_unique<Exporter>(guids, uint32(interval), file,
                sConfigMgr->GetBoolDefault("ContextAPI.DiagnosticDetails", false),
                sConfigMgr->GetBoolDefault("ContextAPI.ActionHistory", false),
                sConfigMgr->GetBoolDefault("ContextAPI.Movement", false));
            Service->Start();
            TC_LOG_INFO("module.context", "Read-only Context API enabled for %u characters at %u ms.", uint32(guids.size()), uint32(interval));
        }
        catch (std::exception const& error)
        { Service.reset(); TC_LOG_ERROR("module.context", "Context API startup failed: %s", error.what()); }
    }
    void OnShutdown() override { if (Service) Service->Stop(); }
};

class ContextPlayers final : public PlayerScript
{
public:
    ContextPlayers() : PlayerScript("ContextAPIPlayers") { }
    void OnLogin(Player* player, bool) override
    {
        if (Service && Service->Enabled()) Service->Rows().Login(player->GetGUID().GetRawValue(), Service->Now(), WallMs());
    }
    void OnLogout(Player* player) override
    {
        if (Service && Service->Enabled()) Service->Rows().Logout(player->GetGUID().GetRawValue(), Service->Now(), WallMs());
    }
    void OnUpdate(Player* player, uint32) override
    {
        if (!Service || !Service->Enabled()) return;
        uint64 now = Service->Now(), guid = player->GetGUID().GetRawValue();
        auto generation = Service->Rows().Due(guid, now);
        if (!generation) return;
        Sample row; row.Guid = guid; row.Generation = *generation;
        row.SampledMs = now; row.WallMs = WallMs();
        row.State = player->IsBeingTeleported() ? "transferring" : "online";
        // During transfer do not read engine or location as a settled state.
        if (row.State == "transferring") { Service->Rows().Publish(std::move(row)); return; }
        WorldSession* session = player->GetSession();
        if (!session) return;
        row.HasPlayer = true; row.Name = player->GetName(); row.IsBot = session->IsServerOrigin();
        row.Alive = player->IsAlive(); row.Combat = player->IsInCombat();
        row.Target = player->GetTarget().GetRawValue(); row.Map = player->GetMapId(); row.Instance = player->GetInstanceId();
        row.Health = player->GetHealth(); row.MaxHealth = player->GetMaxHealth();
        auto power = player->GetPowerType(); row.PowerType = uint32(power);
        row.Power = player->GetPower(power); row.MaxPower = player->GetMaxPower(power);
        row.X = player->GetPositionX(); row.Y = player->GetPositionY(); row.Z = player->GetPositionZ(); row.Orientation = player->GetOrientation();
        // Copy group identity only, never enumerate cross-map member objects.
        if (Group* group = player->GetGroup()) row.Group = group->GetGUID().GetRawValue();
        if (Service->Movement())
        {
            row.Movement = true; row.MovementFlags = player->GetUnitMovementFlags();
            row.Falling = player->HasUnitMovementFlag(MOVEMENTFLAG_FALLING | MOVEMENTFLAG_FALLING_FAR);
            row.RunSpeed = player->GetSpeed(MOVE_RUN); row.SwimSpeed = player->GetSpeed(MOVE_SWIM);
            row.FlightSpeed = player->GetSpeed(MOVE_FLIGHT);
        }
        if (Service->Diagnostics())
        {
            row.Diagnostics = true; row.Phase = CopyPhase(*player);
            Unit* selected = row.Target ? ObjectAccessor::GetUnit(*player, player->GetTarget()) : nullptr;
            row.SelectedUnit = CopyRelation(*player, row.Target, selected);
            Unit* victim = player->GetVictim();
            row.AttackVictim = CopyRelation(*player, victim ? victim->GetGUID().GetRawValue() : 0, victim);
            for (uint64 peerGuid : Service->Guids())
            {
                if (peerGuid == guid) continue;
                PeerPhase peer; peer.Guid = peerGuid;
                if (Player* other = player->GetMap()->GetPlayer(ObjectGuid(peerGuid)))
                    if (other->IsInWorld())
                    {
                        peer.Available = true; peer.CanSeePhase = player->IsInPhase(other);
                        peer.ReverseCanSeePhase = other->IsInPhase(player);
                    }
                row.Peers.push_back(peer);
            }
        }
        if (row.IsBot)
        {
            uint32 controller = session->GetServerOriginPartyControllerGuidLow();
            uint32 follow = session->GetServerOriginFollowTargetGuidLow();
            row.Controller = controller ? ObjectGuid::Create<HighGuid::Player>(controller).GetRawValue() : 0;
            row.FollowTarget = follow ? ObjectGuid::Create<HighGuid::Player>(follow).GetRawValue() : 0;
            row.RoleMask = session->GetPlayerbotStrategyRoleMask(); row.AttackRequested = session->IsServerOriginAttacking();
            row.Bot = session->GetPlayerbotContextStateForMap();
            if (Service->History())
            {
                row.History = std::move(row.Bot.ActionHistory); row.HistoryGeneration = row.Generation;
                row.HistorySampledMs = row.SampledMs; row.HistoryWallMs = row.WallMs;
            }
        }
        Service->Rows().Publish(std::move(row));
    }
};
}

void AddSC_context_api()
{
    new CataContext::ContextWorld();
    new CataContext::ContextPlayers();
}
