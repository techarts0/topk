/**
 * The full implementations of algorithm Min-Heap-TopK and TFA-TopK.
 */
#include <algorithm>
#include <iostream>
#include <vector>
#include <queue>
#include <random>
#include <chrono>
#include <cstdint>
#include <climits>
#include <cstring>

void update(int result[], int k) {
    int key = result[0];
    int* pos = std::lower_bound(result + 1, result + k, key);
    int point = pos - result;
    memmove(result, result + 1, (point - 1) * sizeof(int));
    result[point - 1] = key;
}


void tfarray_topk(int target[], int length, int k, int result[]) {
    memmove(result, target, k * sizeof(int));
    std::sort(result, result + k);
    for (int i = k; i < length; i++) {
        if (target[i] <= result[0]) { //Filter (The threshold Ratchet)
            continue;
        }
	    result[0] = target[i];
        if (result[0] > result[1]) {
            update(result, k);
        }
    }
}


 void minheap_topk(int src[], int length, int k, int result[]) {
    std::vector<int> container;
    container.reserve(k);
    std::copy(src, src + k, std::back_inserter(container));

    std::make_heap(container.begin(), container.end(), std::greater<int>());
    std::priority_queue<int, std::vector<int>, std::greater<int>> minHeap(
        std::greater<int>(), std::move(container));

    for (int i = k; i < length; i++) {
        if (src[i] > minHeap.top()) { //Filter (The threshold Ratchet)
            minHeap.pop();
            minHeap.push(src[i]);
        }
    }
        
    for (int i = 0; i < k; i++) { // Sorting the result ASC
        result[k - i - 1] = minHeap.top(); 
        minHeap.pop();
    }
}