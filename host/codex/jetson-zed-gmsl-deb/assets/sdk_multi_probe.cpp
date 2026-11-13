#include <sl/Camera.hpp>
#include <sl/CameraOne.hpp>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace {

std::atomic<int> ready_count{0};
std::atomic<bool> start_open{false};
std::mutex log_mutex;

void log_line(const std::string& line) {
    std::lock_guard<std::mutex> lock(log_mutex);
    std::cerr << line << std::endl;
}

struct Result {
    std::string kind;
    std::uint64_t serial = 0;
    int open_code = -1;
    int successful_grabs = 0;
    int first_grab_error = 0;
};

void wait_for_start() {
    ++ready_count;
    while (!start_open.load(std::memory_order_acquire))
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
}

void run_one(std::uint64_t serial, int frames, Result* result) {
    result->kind = "one";
    result->serial = serial;
    wait_for_start();

    sl::CameraOne camera;
    sl::InitParametersOne init;
    init.sdk_verbose = 1;
    init.camera_resolution = sl::RESOLUTION::HD1200;
    init.camera_fps = 15;
    init.async_grab_camera_recovery = true;
    init.input.setFromSerialNumber(serial);

    log_line("OPEN one serial=" + std::to_string(serial));
    const auto status = camera.open(init);
    result->open_code = static_cast<int>(status);
    log_line("OPEN_RESULT one serial=" + std::to_string(serial) + " code=" +
             std::to_string(result->open_code) + " " + sl::toString(status).get());
    if (status > sl::ERROR_CODE::SUCCESS)
        return;

    for (int i = 0; i < frames; ++i) {
        const auto grab_status = camera.grab();
        if (grab_status > sl::ERROR_CODE::SUCCESS) {
            result->first_grab_error = static_cast<int>(grab_status);
            log_line("GRAB_ERROR one serial=" + std::to_string(serial) +
                     " frame=" + std::to_string(i) + " code=" +
                     std::to_string(result->first_grab_error) + " " +
                     sl::toString(grab_status).get());
            break;
        }
        ++result->successful_grabs;
    }
    camera.close();
}

void run_stereo(std::uint64_t serial, int frames, Result* result) {
    result->kind = "stereo";
    result->serial = serial;
    wait_for_start();

    sl::Camera camera;
    sl::InitParameters init;
    init.sdk_verbose = 1;
    init.camera_resolution = sl::RESOLUTION::HD1200;
    init.camera_fps = 30;
    init.depth_mode = sl::DEPTH_MODE::NONE;
    init.async_grab_camera_recovery = true;
    init.input.setFromSerialNumber(serial);

    log_line("OPEN stereo serial=" + std::to_string(serial));
    const auto status = camera.open(init);
    result->open_code = static_cast<int>(status);
    log_line("OPEN_RESULT stereo serial=" + std::to_string(serial) + " code=" +
             std::to_string(result->open_code) + " " + sl::toString(status).get());
    if (status > sl::ERROR_CODE::SUCCESS)
        return;

    for (int i = 0; i < frames; ++i) {
        const auto grab_status = camera.grab();
        if (grab_status > sl::ERROR_CODE::SUCCESS) {
            result->first_grab_error = static_cast<int>(grab_status);
            log_line("GRAB_ERROR stereo serial=" + std::to_string(serial) +
                     " frame=" + std::to_string(i) + " code=" +
                     std::to_string(result->first_grab_error) + " " +
                     sl::toString(grab_status).get());
            break;
        }
        ++result->successful_grabs;
    }
    camera.close();
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 4) {
        std::cerr << "Usage: " << argv[0]
                  << " FRAMES one:SERIAL|stereo:SERIAL [...]\n";
        return 2;
    }

    const int frames = std::stoi(argv[1]);
    std::vector<std::string> specs;
    for (int i = 2; i < argc; ++i)
        specs.emplace_back(argv[i]);

    std::vector<Result> results(specs.size());
    std::vector<std::thread> threads;
    threads.reserve(specs.size());

    for (std::size_t i = 0; i < specs.size(); ++i) {
        const auto separator = specs[i].find(':');
        if (separator == std::string::npos) {
            std::cerr << "Invalid camera spec: " << specs[i] << '\n';
            return 2;
        }
        const std::string kind = specs[i].substr(0, separator);
        const auto serial = std::stoull(specs[i].substr(separator + 1));
        if (kind == "one")
            threads.emplace_back(run_one, serial, frames, &results[i]);
        else if (kind == "stereo")
            threads.emplace_back(run_stereo, serial, frames, &results[i]);
        else {
            std::cerr << "Invalid camera type: " << kind << '\n';
            return 2;
        }
    }

    while (ready_count.load() != static_cast<int>(threads.size()))
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    start_open.store(true, std::memory_order_release);

    for (auto& thread : threads)
        thread.join();

    bool passed = true;
    std::cerr << "SUMMARY\n";
    for (const auto& result : results) {
        std::cerr << result.kind << " serial=" << result.serial
                  << " open=" << result.open_code
                  << " grabs=" << result.successful_grabs
                  << " grab_error=" << result.first_grab_error << '\n';
        if (result.open_code != 0 || result.successful_grabs != frames)
            passed = false;
    }
    return passed ? 0 : 1;
}
