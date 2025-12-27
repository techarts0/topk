#include <iostream>
#include <random>
#include <chrono>
#include <climits>
#include <cstdint>
#include <string>

#include <linux/perf_event.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include <sys/syscall.h>

#include "test_dataset.cpp"
#include "topk_component.cpp"

static long perf_event_open(struct perf_event_attr *hw_event, pid_t pid,
                           int cpu, int group_fd, unsigned long flags) {
    return syscall(__NR_perf_event_open, hw_event, pid, cpu, group_fd, flags);
}

/**
 * args:
 * index 1: N, the total count of processed elements in the stream
 * index 2: k, the scale of top k
 * index 3: algorithm (1: TFA-TopK, 2: MinHeap-TopK)
 */
int main(int argc, char** argv){
    
    int k = atoi(argv[2]);
    int scale = atoi(argv[1]);
    
    int algo = atoi(argv[3]);
    
    int fd[6];
    long long counts[6];
    struct perf_event_attr attr[6];
    const char* metric_names[] = {
        "CPU cycles", "Instructions", "Cache Refs", "Cache misses", "Branches", "Branch misses"
    };
    int configs[] = {
        PERF_COUNT_HW_CPU_CYCLES,
        PERF_COUNT_HW_INSTRUCTIONS,
        PERF_COUNT_HW_CACHE_REFERENCES,
        PERF_COUNT_HW_CACHE_MISSES,
        PERF_COUNT_HW_BRANCH_INSTRUCTIONS,
        PERF_COUNT_HW_BRANCH_MISSES
        //PERF_COUNT_HW_STALLED_CYCLES_FRONTEND,
        //PERF_COUNT_HW_STALLED_CYCLES_BACKEND
    };


    // Initialize all performance events
    for (int i = 0; i < 6; i++) {
        memset(&attr[i], 0, sizeof(attr[i]));
        attr[i].type = PERF_TYPE_HARDWARE;
        attr[i].size = sizeof(attr[i]);
        attr[i].config = configs[i];
        attr[i].disabled = 1;
        attr[i].exclude_kernel = 1;
        attr[i].exclude_hv = 1;

        // Group the events (the first event is leader)
        fd[i] = perf_event_open(&attr[i], 0, -1, i == 0 ? -1 : fd[0], 0);
        if (fd[i] < 0) {
            perror("perf_event_open");
	    std::cout << i << std::endl;
            // Close all opened file descriptors
            for (int j = 0; j < i; j++) close(fd[j]);
            return 0;
        }
    }

    int rounds = 100;
    int* target = new int[scale];
    generate_dataset(target, scale);
    
    int* result = new int[k];

    //Warmup
    switch(algo){
        case 1:
            for(int i = 0; i < 50; i++){
                tfarray(target, scale, k, result);
            }
            break;
        case 2:
            for(int i = 0; i < 50; i++){
                minheap(target, scale, k, result);
            }
            break;
        default:
            break;
    }
    
    // Enable all performance events (only group leader)
    ioctl(fd[0], PERF_EVENT_IOC_RESET, PERF_IOC_FLAG_GROUP);
    ioctl(fd[0], PERF_EVENT_IOC_ENABLE, PERF_IOC_FLAG_GROUP);
    
    //Executing the algorithms
    switch(algo){
	    case 1:
     		for(int i =0; i < rounds; i++){
        	    tfarray(target, scale, k, result);
    		}
		    break;
	    case 2:
            for(int i =0; i < rounds; i++){
                minheap(target, scale, k, result);
            }
            break;
        default:
            break;
		return 0;
    }

    
    // Disable the performance events
    ioctl(fd[0], PERF_EVENT_IOC_DISABLE, PERF_IOC_FLAG_GROUP);

    // Output all performance counting results
    for (int i = 0; i < 6; i++) {
        ssize_t bytes_read = read(fd[i], &counts[i], sizeof(counts[i]));
        if (bytes_read != sizeof(counts[i])) {
            perror("Failed to read performance counter");
        } else {
            printf("%s: %lld\n", metric_names[i], counts[i]);
        }
        close(fd[i]);
    }


    delete[] result;
    delete[] target;
    return 0;
}

