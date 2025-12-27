#include <iostream>
#include <random>
#include <chrono>
#include <climits>
#include <cstdint>
#include <string>

#include "test_dataset.cpp"
#include "topk_component.cpp"

/**
 * args:
 * index 1: N, the total count of processed elements in the stream
 * index 2: k, the scale of top k
 */
int main(int argc, char** argv){
    int k = atoi(argv[2]);
    int scale = atoi(argv[1]);
    
    int warmup = 50, rounds = 501;
    int* target = new int[scale];
    generate_dataset(target, scale);
    
    int* result = new int[k];
    
    long* counts = new long[rounds];

    //TFA
     for(int i =0; i < warmup; i++){
        tfarray(target, scale, k, result);
    }

    
    for(int i =0; i < rounds; i++){
        auto start = std::chrono::high_resolution_clock::now();
	    tfarray(target, scale, k, result);
        auto end = std::chrono::high_resolution_clock::now();
        auto duration = end - start;
        counts[i] = std::chrono::duration_cast<std::chrono::nanoseconds>(duration).count();     
    }
    std::cout << "TFA (Median): " << calc_median(counts, rounds) << " ns\n";
    

    //MinHeap
    memset(counts, 0, rounds);

    for(int i =0; i < warmup; i++){
        minheap(target, scale, k, result);
    }

    for(int i =0; i < rounds; i++){
        auto start = std::chrono::high_resolution_clock::now();
	    minheap(target, scale, k, result);
	    auto end = std::chrono::high_resolution_clock::now();
        auto duration = end - start;
        counts[i] = std::chrono::duration_cast<std::chrono::nanoseconds>(duration).count();
    }
    std::cout << "Min-Heap (Median): " << calc_median(counts, rounds) << " ns\n";
   
    delete[] result;
    delete[] target;
    delete[] counts;
    return 0;
}

