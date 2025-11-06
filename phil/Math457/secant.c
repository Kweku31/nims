#include<stdio.h>
#include<math.h>

#define FN(x) ((x*x*x)-x-1)

int main(){
float c;
float a=1;
float b=3;
float u;
	while(fabs(FN(u))>=0.000001){
	u = a -((b-a)/(FN(b)-FN(a)))*FN(a);
	a=b;
	b=u;
	}
	printf("The root of the function is %f\n",u);


}
