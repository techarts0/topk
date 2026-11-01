#include "duckdb.h"

#include <cstdint>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {
void query_ok(duckdb_connection con, const std::string &sql) {
	duckdb_result result{};
	if (duckdb_query(con, sql.c_str(), &result) != DuckDBSuccess) {
		std::string message = duckdb_result_error(&result) ? duckdb_result_error(&result) : "unknown DuckDB error";
		duckdb_destroy_result(&result);
		throw std::runtime_error(sql + ": " + message);
	}
	duckdb_destroy_result(&result);
}

uint64_t hash_query(duckdb_connection con, const std::string &sql, idx_t expected_rows) {
	duckdb_result result{};
	if (duckdb_query(con, sql.c_str(), &result) != DuckDBSuccess) {
		std::string message = duckdb_result_error(&result) ? duckdb_result_error(&result) : "unknown DuckDB error";
		duckdb_destroy_result(&result);
		throw std::runtime_error(sql + ": " + message);
	}
	if (duckdb_row_count(&result) != expected_rows) {
		duckdb_destroy_result(&result);
		throw std::runtime_error("unexpected result cardinality: " + sql);
	}
	uint64_t hash = 1469598103934665603ULL;
	for (idx_t row = 0; row < expected_rows; row++) {
		uint64_t bits;
		if (duckdb_value_is_null(&result, 0, row)) {
			bits = UINT64_MAX;
		} else {
			double value = duckdb_value_double(&result, 0, row);
			std::memcpy(&bits, &value, sizeof(bits));
		}
		for (int byte = 0; byte < 8; byte++) {
			hash = (hash ^ static_cast<uint8_t>(bits & 0xffU)) * 1099511628211ULL;
			bits >>= 8;
		}
	}
	duckdb_destroy_result(&result);
	return hash;
}
} // namespace

int main() {
	duckdb_database db = nullptr;
	duckdb_connection con = nullptr;
	if (duckdb_open(nullptr, &db) != DuckDBSuccess || duckdb_connect(db, &con) != DuckDBSuccess) {
		throw std::runtime_error("could not initialize DuckDB");
	}
	query_ok(con, "SET threads=1");
	query_ok(con, "CREATE TABLE finite_ties AS SELECT (i % 7)::DOUBLE AS score, i::INTEGER AS id FROM range(10000) t(i)");
	query_ok(con, "CREATE TABLE finite_distinct AS SELECT ((i * 7919) % 10007)::DOUBLE AS score, i::INTEGER AS id FROM range(10000) t(i)");
	query_ok(con, "CREATE TABLE nan_candidate AS SELECT CASE WHEN i % 113 = 0 THEN 'NaN'::DOUBLE ELSE (i % 811)::DOUBLE END AS score, i::INTEGER AS id FROM range(10000) t(i)");
	query_ok(con, "CREATE TABLE nan_boundary AS SELECT CASE WHEN i % 3 = 0 THEN 'NaN'::DOUBLE ELSE (i % 811)::DOUBLE END AS score, i::INTEGER AS id FROM range(10000) t(i)");
	query_ok(con, "CREATE TABLE null_fallback AS SELECT CASE WHEN i % 13 = 0 THEN NULL::DOUBLE WHEN i % 113 = 0 THEN 'NaN'::DOUBLE ELSE (i % 811)::DOUBLE END AS score, i::INTEGER AS id FROM range(10000) t(i)");

	const std::vector<std::pair<std::string, std::string>> cases = {
	    {"finite_ties", "SELECT score FROM finite_ties ORDER BY score DESC LIMIT 100"},
	    {"finite_distinct", "SELECT score FROM finite_distinct ORDER BY score DESC LIMIT 100"},
	    {"nan_candidate", "SELECT score FROM nan_candidate ORDER BY score DESC LIMIT 100"},
	    {"nan_boundary", "SELECT score FROM nan_boundary ORDER BY score DESC LIMIT 100"},
	    {"null_fallback", "SELECT score FROM null_fallback ORDER BY score DESC NULLS LAST LIMIT 100"},
	    {"ascending_fallback", "SELECT score FROM finite_distinct ORDER BY score ASC LIMIT 100"},
	    {"offset_fallback", "SELECT score FROM finite_distinct ORDER BY score DESC LIMIT 100 OFFSET 7"},
	    {"multikey_fallback", "SELECT score FROM finite_ties ORDER BY score DESC, id DESC LIMIT 100"},
	    {"large_k_fallback", "SELECT score FROM finite_distinct ORDER BY score DESC LIMIT 101"},
	};
	for (const auto &test : cases) {
		const idx_t rows = test.first == "offset_fallback" ? 100 :
		                   test.first == "large_k_fallback" ? 101 : 100;
		std::cout << test.first << ',' << rows << ',' << hash_query(con, test.second, rows) << '\n';
	}
	query_ok(con, "SET threads=4");
	const std::string parallel_query =
	    "SELECT (i % 100003)::DOUBLE AS score FROM range(1000000) t(i) ORDER BY score DESC LIMIT 100";
	std::cout << "parallel_combine,100," << hash_query(con, parallel_query, 100) << '\n';
	duckdb_disconnect(&con);
	duckdb_close(&db);
	return 0;
}
