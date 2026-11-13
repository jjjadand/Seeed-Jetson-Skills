#include <sl/Camera.hpp>
#include <iostream>
int main(int argc,char** argv) {
 std::cerr << "SDK " << sl::Camera::getSDKVersion() << std::endl;
 for (const auto &d:sl::Camera::getDeviceList()) std::cerr<<"DEVICE serial="<<d.serial_number<<" model="<<sl::toString(d.camera_model)<<" state="<<sl::toString(d.camera_state)<<std::endl;
 if(argc<2)return 0;
 sl::Camera c;sl::InitParameters p;p.sdk_verbose=1;p.camera_resolution=sl::RESOLUTION::HD1200;p.camera_fps=30;p.depth_mode=sl::DEPTH_MODE::NONE;p.input.setFromSerialNumber(std::stoul(argv[1]));
 auto status=c.open(p);std::cerr<<"OPEN "<<sl::toString(status)<<std::endl;if(status!=sl::ERROR_CODE::SUCCESS)return 1;
 int success=0;sl::Mat im;
 for(int i=0;i<300;i++){auto g=c.grab();if(g!=sl::ERROR_CODE::SUCCESS){std::cerr<<"GRAB_ERROR "<<sl::toString(g)<<std::endl;break;}if(i==0){auto r=c.retrieveImage(im,sl::VIEW::LEFT,sl::MEM::CPU);std::cerr<<"IMAGE "<<sl::toString(r)<<" "<<im.getWidth()<<"x"<<im.getHeight()<<std::endl;}success++;}
 c.close();std::cerr<<"FRAMES "<<success<<"/300"<<std::endl;return success==300?0:2;
}
