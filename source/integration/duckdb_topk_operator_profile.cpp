#include "duckdb.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <functional>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr idx_t kVectorSize = 2048;

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
        const double value = std::stod(line, &used);
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
    const auto state = duckdb_query(con, sql.c_str(), &result);
    if (state != DuckDBSuccess) {
        const std::string message = duckdb_result_error(&result) ? duckdb_result_error(&result) : "unknown query error";
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
            if (value) {
                out << value << '\n';
                duckdb_free(value);
            }
        }
    }
    duckdb_destroy_result(&result);
    return out.str();
}

void load_table(duckdb_connection con, const std::vector<double> &values) {
    query_ok(con, "CREATE TABLE topk_input(score DOUBLE NOT NULL)");
    duckdb_appender appender = nullptr;
    check(duckdb_appender_create(con, nullptr, "topk_input", &appender), "create appender");
    duckdb_logical_type type = duckdb_create_logical_type(DUCKDB_TYPE_DOUBLE);
    duckdb_data_chunk chunk = duckdb_create_data_chunk(&type, 1);
    if (!chunk) throw std::runtime_error("could not allocate DuckDB data chunk");
    duckdb_destroy_logical_type(&type);
    for (size_t begin = 0; begin < values.size(); begin += kVectorSize) {
        const idx_t count = static_cast<idx_t>(std::min<size_t>(kVectorSize, values.size() - begin));
        duckdb_data_chunk_reset(chunk);
        auto vector = duckdb_data_chunk_get_vector(chunk, 0);
        auto *data = static_cast<double *>(duckdb_vector_get_data(vector));
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

std::string metric_string(duckdb_profiling_info info, const char *key) {
    duckdb_value value = duckdb_profiling_info_get_value(info, key);
    if (!value) return {};
    char *text = duckdb_get_varchar(value);
    std::string result = text ? text : "";
    if (text) duckdb_free(text);
    duckdb_destroy_value(&value);
    return result;
}

double metric_double(duckdb_profiling_info info, const char *key) {
    const auto value = metric_string(info, key);
    if (value.empty()) throw std::runtime_error(std::string("missing profile metric: ") + key);
    size_t used = 0;
    const double result = std::stod(value, &used);
    if (used != value.size() || !std::isfinite(result))
        throw std::runtime_error(std::string("invalid profile metric: ") + key + "=" + value);
    return result;
}

void collect_topn(duckdb_profiling_info info, double &seconds, idx_t &nodes) {
    const auto type = metric_string(info, "OPERATOR_TYPE");
    if (type == "TOP_N") {
        seconds += metric_double(info, "OPERATOR_TIMING");
        ++nodes;
    }
    const idx_t children = duckdb_profiling_info_get_child_count(info);
    for (idx_t i = 0; i < children; ++i) {
        auto child = duckdb_profiling_info_get_child(info, i);
        if (child) collect_topn(child, seconds, nodes);
    }
}

struct Observation {
    int64_t elapsed_ns;
    int64_t topn_ns;
    int64_t root_latency_ns;
    uint64_t checksum;
    idx_t rows;
    idx_t topn_nodes;
};

Observation run_profiled_query(duckdb_connection con, const std::string &sql,
                               const std::vector<double> &expected) {
    duckdb_result result{};
    const auto start = std::chrono::steady_clock::now();
    const auto state = duckdb_query(con, sql.c_str(), &result);
    if (state != DuckDBSuccess) {
        const std::string message = duckdb_result_error(&result) ? duckdb_result_error(&result) : "unknown query error";
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
    const auto stop = std::chrono::steady_clock::now();
    if (values != expected) throw std::runtime_error("query output differs from full-sort reference");

    auto profile = duckdb_get_profiling_info(con);
    if (!profile) throw std::runtime_error("DuckDB profiling tree is unavailable");
    double topn_seconds = 0.0;
    idx_t topn_nodes = 0;
    collect_topn(profile, topn_seconds, topn_nodes);
    if (topn_nodes != 1) throw std::runtime_error("expected exactly one TOP_N profiling node");
    const double root_latency = metric_double(profile, "LATENCY");
    return {
        std::chrono::duration_cast<std::chrono::nanoseconds>(stop - start).count(),
        static_cast<int64_t>(std::llround(topn_seconds * 1e9)),
        static_cast<int64_t>(std::llround(root_latency * 1e9)),
        hash_values(values),
        static_cast<idx_t>(values.size()),
        topn_nodes,
    };
}

std::string csv_escape(const std::string &text) {
    std::string result = "\"";
    for (char c : text) {
        if (c == '"') result += '"';
        result += c;
    }
    return result + '"';
}
} // namespace

int main(int argc, char **argv) {
    try {
        if (argc != 6)
            throw std::runtime_error("usage: duckdb_topk_operator_profile DATA.csv K REPS VARIANT PLAN.txt");
        const std::string data_path = argv[1];
        const idx_t k = static_cast<idx_t>(std::stoull(argv[2]));
        const int reps = std::stoi(argv[3]);
        const std::string variant = argv[4];
        const std::string plan_path = argv[5];
        if (reps < 1 || k < 1) throw std::runtime_error("K and REPS must be positive");

        const auto scores = load_scores(data_path);
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
        const std::string sql = "SELECT score FROM topk_input ORDER BY score DESC LIMIT " + std::to_string(k);
        const auto plan = query_text(con, "EXPLAIN " + sql);
        if (plan.find("TOP_N") == std::string::npos)
            throw std::runtime_error("expected TOP_N plan; actual plan saved to requested plan file");
        std::ofstream plan_file(plan_path);
        if (!plan_file) throw std::runtime_error("cannot write plan file: " + plan_path);
        plan_file << plan;
        plan_file.close();

        // Standard profiling collects OPERATOR_TIMING for each physical operator.
        query_ok(con, "PRAGMA enable_profiling='no_output'");
        const auto warmup = run_profiled_query(con, sql, expected);
        (void)warmup;

        std::cout << "variant,data,k,rep,elapsed_ns,topn_operator_ns,root_latency_ns,rows,checksum,topn_nodes\n";
        for (int rep = 0; rep < reps; ++rep) {
            const auto obs = run_profiled_query(con, sql, expected);
            std::cout << variant << ',' << csv_escape(data_path) << ',' << k << ',' << rep << ','
                      << obs.elapsed_ns << ',' << obs.topn_ns << ',' << obs.root_latency_ns << ','
                      << obs.rows << ',' << obs.checksum << ',' << obs.topn_nodes << '\n';
        }
        duckdb_disconnect(&con);
        duckdb_close(&db);
        return 0;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
