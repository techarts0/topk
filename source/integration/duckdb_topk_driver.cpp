#include "duckdb.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <functional>
#include <iostream>
#include <linux/perf_event.h>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <vector>

namespace {
constexpr idx_t kVectorSize = 2048; // DuckDB v1.4.0 STANDARD_VECTOR_SIZE.

struct Counters {
    std::array<int, 4> fds{{-1, -1, -1, -1}};
    bool available = false;

    static int open_event(uint64_t config, int group_fd) {
        perf_event_attr attr{};
        attr.type = PERF_TYPE_HARDWARE;
        attr.size = sizeof(attr);
        attr.config = config;
        attr.disabled = group_fd < 0;
        attr.exclude_kernel = 1;
        attr.exclude_hv = 1;
        if (group_fd < 0)
            attr.read_format = PERF_FORMAT_GROUP | PERF_FORMAT_TOTAL_TIME_ENABLED |
                               PERF_FORMAT_TOTAL_TIME_RUNNING;
        return static_cast<int>(syscall(SYS_perf_event_open, &attr, 0, -1, group_fd, 0));
    }

    Counters() {
        const std::array<uint64_t, 4> events{{PERF_COUNT_HW_CPU_CYCLES,
                                              PERF_COUNT_HW_INSTRUCTIONS,
                                              PERF_COUNT_HW_BRANCH_INSTRUCTIONS,
                                              PERF_COUNT_HW_BRANCH_MISSES}};
        for (size_t i = 0; i < events.size(); ++i) {
            fds[i] = open_event(events[i], i == 0 ? -1 : fds[0]);
            if (fds[i] < 0) {
                for (int fd : fds) if (fd >= 0) close(fd);
                fds.fill(-1);
                return;
            }
        }
        available = true;
    }

    ~Counters() { for (int fd : fds) if (fd >= 0) close(fd); }
    void start() {
        if (!available) return;
        ioctl(fds[0], PERF_EVENT_IOC_RESET, PERF_IOC_FLAG_GROUP);
        ioctl(fds[0], PERF_EVENT_IOC_ENABLE, PERF_IOC_FLAG_GROUP);
    }
    void stop() {
        if (available) ioctl(fds[0], PERF_EVENT_IOC_DISABLE, PERF_IOC_FLAG_GROUP);
    }
    std::array<uint64_t, 7> read() const {
        std::array<uint64_t, 7> output{};
        if (!available) return output;
        const ssize_t n = ::read(fds[0], output.data(), sizeof(output));
        if (n != static_cast<ssize_t>(sizeof(output)))
            throw std::runtime_error("short read from perf event group");
        return output; // nr, time_enabled, time_running, and four event values.
    }
};

std::vector<double> load_scores(const std::string &path) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("cannot open input: " + path);
    std::string line;
    if (!std::getline(in, line))
        throw std::runtime_error("expected CSV header score");
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (line != "score")
        throw std::runtime_error("expected CSV header score");
    std::vector<double> values;
    values.reserve(1'000'000);
    while (std::getline(in, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        size_t used = 0;
        double value = std::stod(line, &used);
        if (used != line.size() || !std::isfinite(value))
            throw std::runtime_error("invalid/nonfinite score in CSV");
        values.push_back(value);
    }
    return values;
}

void check(duckdb_state state, const char *what) {
    if (state != DuckDBSuccess) throw std::runtime_error(std::string("DuckDB error: ") + what);
}

void query_ok(duckdb_connection con, const std::string &sql) {
    duckdb_result result{};
    duckdb_state state = duckdb_query(con, sql.c_str(), &result);
    if (state != DuckDBSuccess) {
        std::string message = duckdb_result_error(&result) ? duckdb_result_error(&result) : "unknown query error";
        duckdb_destroy_result(&result);
        throw std::runtime_error(sql + ": " + message);
    }
    duckdb_destroy_result(&result);
}

std::string query_text(duckdb_connection con, const std::string &sql) {
    duckdb_result result{};
    check(duckdb_query(con, sql.c_str(), &result), "EXPLAIN");
    std::ostringstream out;
    for (idx_t row = 0; row < duckdb_row_count(&result); ++row) {
        for (idx_t col = 0; col < duckdb_column_count(&result); ++col) {
            char *value = duckdb_value_varchar(&result, col, row);
            if (value) { out << value << '\n'; duckdb_free(value); }
        }
    }
    duckdb_destroy_result(&result);
    return out.str();
}

void load_table(duckdb_connection con, const std::vector<double> &values) {
    query_ok(con, "CREATE TABLE topk_input(score DOUBLE NOT NULL)");
    duckdb_appender appender = nullptr;
    check(duckdb_appender_create(con, nullptr, "topk_input", &appender), "create appender");
    duckdb_logical_type double_type = duckdb_create_logical_type(DUCKDB_TYPE_DOUBLE);
    duckdb_data_chunk chunk = duckdb_create_data_chunk(&double_type, 1);
    if (!chunk) throw std::runtime_error("could not allocate DuckDB data chunk");
    duckdb_destroy_logical_type(&double_type);
    duckdb_vector vector = duckdb_data_chunk_get_vector(chunk, 0);
    auto *data = static_cast<double *>(duckdb_vector_get_data(vector));
    for (size_t begin = 0; begin < values.size(); begin += kVectorSize) {
        const idx_t count = static_cast<idx_t>(std::min<size_t>(kVectorSize, values.size() - begin));
        duckdb_data_chunk_reset(chunk);
        vector = duckdb_data_chunk_get_vector(chunk, 0);
        data = static_cast<double *>(duckdb_vector_get_data(vector));
        std::copy_n(values.data() + begin, count, data);
        duckdb_data_chunk_set_size(chunk, count);
        check(duckdb_append_data_chunk(appender, chunk), "append data chunk");
    }
    check(duckdb_appender_flush(appender), "flush appender");
    check(duckdb_appender_close(appender), "close appender");
    duckdb_appender_destroy(&appender);
    duckdb_destroy_data_chunk(&chunk);
}

uint64_t hash_values(const std::vector<double> &values) {
    uint64_t hash = 1469598103934665603ULL;
    for (double value : values) {
        uint64_t bits;
        std::memcpy(&bits, &value, sizeof(bits));
        for (int i = 0; i < 8; ++i) {
            hash = (hash ^ static_cast<unsigned char>(bits & 0xffU)) * 1099511628211ULL;
            bits >>= 8;
        }
    }
    return hash;
}

std::vector<double> fetch_result(duckdb_connection con, const std::string &sql) {
    duckdb_result result{};
    duckdb_state state = duckdb_query(con, sql.c_str(), &result);
    if (state != DuckDBSuccess) {
        std::string message = duckdb_result_error(&result) ? duckdb_result_error(&result) : "unknown query error";
        duckdb_destroy_result(&result);
        throw std::runtime_error(message);
    }
    std::vector<double> values;
    values.reserve(static_cast<size_t>(duckdb_row_count(&result)));
    for (idx_t row = 0; row < duckdb_row_count(&result); ++row) {
        if (duckdb_value_is_null(&result, 0, row)) {
            duckdb_destroy_result(&result);
            throw std::runtime_error("unexpected NULL in Top-N output");
        }
        values.push_back(duckdb_value_double(&result, 0, row));
    }
    duckdb_destroy_result(&result);
    return values;
}

std::string escape_csv(const std::string &value) {
    std::string out = "\"";
    for (char c : value) { if (c == '"') out += '"'; out += c; }
    return out + '"';
}
} // namespace

int main(int argc, char **argv) {
    try {
        if (argc != 5) throw std::runtime_error("usage: duckdb_topk_driver DATA.csv K REPS PLAN.txt");
        const std::string data_path = argv[1];
        const idx_t k = static_cast<idx_t>(std::stoull(argv[2]));
        const int reps = std::stoi(argv[3]);
        const std::string plan_path = argv[4];
        if (reps < 1 || k < 1) throw std::runtime_error("K and REPS must be positive");

        auto scores = load_scores(data_path);
        if (k > scores.size()) throw std::runtime_error("K exceeds input length");
        auto expected = scores;
        std::sort(expected.begin(), expected.end(), std::greater<double>());
        expected.resize(static_cast<size_t>(k));

        duckdb_database db = nullptr;
        check(duckdb_open(nullptr, &db), "open in-memory database");
        duckdb_connection con = nullptr;
        check(duckdb_connect(db, &con), "connect");
        query_ok(con, "SET threads=1");
        load_table(con, scores);

        const std::string query = "SELECT score FROM topk_input ORDER BY score DESC LIMIT " + std::to_string(k);
        const std::string plan = query_text(con, "EXPLAIN " + query);
        if (plan.find("TOP_N") == std::string::npos)
            throw std::runtime_error("expected TOP_N plan; actual plan saved to requested plan file");
        std::ofstream plan_file(plan_path);
        if (!plan_file) throw std::runtime_error("cannot write plan file: " + plan_path);
        plan_file << plan;
        plan_file.close();

        if (fetch_result(con, query) != expected)
            throw std::runtime_error("warmup result differs from full-sort reference");

        const char *variant_env = std::getenv("TOPK_VARIANT");
        const std::string variant = variant_env ? variant_env : "unspecified";
        std::cout << "variant,data,k,rep,elapsed_ns,rows,checksum,cycles,instructions,branches,branch_misses,perf_running_pct\n";
        for (int rep = 0; rep < reps; ++rep) {
            Counters counters;
            counters.start();
            const auto start = std::chrono::steady_clock::now();
            auto result = fetch_result(con, query);
            const auto stop = std::chrono::steady_clock::now();
            counters.stop();
            auto values = counters.read();
            if (result != expected) throw std::runtime_error("timed query output differs from reference");
            const auto elapsed = std::chrono::duration_cast<std::chrono::nanoseconds>(stop - start).count();
            const uint64_t checksum = hash_values(result);
            std::cout << variant << ',' << escape_csv(data_path) << ',' << k << ',' << rep << ',' << elapsed
                      << ',' << result.size() << ',' << checksum << ',';
            if (counters.available) {
                const double running_pct = values[1] == 0 ? 0.0 : 100.0 * values[2] / values[1];
                const double scale = values[2] == 0 ? 0.0 :
                    static_cast<double>(values[1]) / static_cast<double>(values[2]);
                std::cout << static_cast<uint64_t>(std::llround(values[3] * scale)) << ','
                          << static_cast<uint64_t>(std::llround(values[4] * scale)) << ','
                          << static_cast<uint64_t>(std::llround(values[5] * scale)) << ','
                          << static_cast<uint64_t>(std::llround(values[6] * scale)) << ','
                          << running_pct;
            } else {
                std::cout << "NA,NA,NA,NA,NA";
            }
            std::cout << '\n';
        }
        duckdb_disconnect(&con);
        duckdb_close(&db);
        return 0;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
