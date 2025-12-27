/**
 * Core data structure: Min-Heap and Threshold-Filter Array (TFA).
 * They are running without the threshold filter protection.
 */

#include <queue>
#include <vector>
#include <algorithm>
#include <iostream>
#include <random>
#include <chrono>
#include <cstdint>
#include <climits>
#include <cstring>

//Min-Heap based on std::priority_queque
void minheap(int src[], int length, int k, int result[]) {
   
    std::vector<int> container;
    container.reserve(k);
    std::copy(src, src + k, std::back_inserter(container));

    std::make_heap(container.begin(), container.end(), std::greater<int>());
    std::priority_queue<int, std::vector<int>, std::greater<int>> minHeap(
        std::greater<int>(), std::move(container));

    for (int i = k; i < length; i++) {
        minHeap.push(src[i]);
         minHeap.pop();
    } 
}

//C: The core data structure (An array)
//k: The length of the candidate array
//key: The current element in stream (S)
void update(int result[], int k, int key) {
    int* pos = std::lower_bound(result, result + k, key);
    int point = pos - result;
    if(point > 0){
        memmove(result, result + 1, (point - 1) * sizeof(int));
        result[point - 1] = key;
    }
}

// Threshold-Filter-Array
void tfarray(int target[], int length, int k, int result[]) {
    memmove(result, target, k * sizeof(int));
    std::sort(result, result + k);
    for (int i = k; i < length; i++) {
        update(result, k, target[i]);
    }
}
