/**
 * The IID dataset generator
 */
#include <random>
#include <climits>
#include <algorithm>

//To ensure reproducibility, we can use a fixed seed sequence.
void generate_dataset(int target[], size_t scale) {
    std::random_device rd;
    std::mt19937 gen(rd()); //Seed
    std::uniform_int_distribution<int> dist(INT_MIN, INT_MAX);
    
    for (size_t i = 0; i < scale; ++i) {
        target[i] = dist(gen);
    }
}

//Get the median from results
long calc_median(long counts[], int rounds){
    std::sort(counts, counts + rounds);
    return counts[rounds / 2 + 1];
}