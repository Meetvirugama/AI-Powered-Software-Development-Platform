#include <iostream>
#include <string>
#include <vector>
#include "engine_config.hpp"

#define MAX_THREADS 16

namespace platform {

class WorkerPool {
public:
    explicit WorkerPool(int threads) : thread_count_(threads) {}

    bool dispatchJob(const std::string& job_name) {
        if (job_name.empty()) {
            return false;
        }
        return validateConcurrency(thread_count_);
    }

    bool validateConcurrency(int count) const {
        return count > 0 && count <= MAX_THREADS;
    }

private:
    int thread_count_;
};

int computePoolCapacity(int workers) {
    return workers * 4;
}

} // namespace platform
