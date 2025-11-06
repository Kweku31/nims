#include<stdio.h>
#include<math.h>

#define FN(x) ((x*x*x)-x-1)

int main(){
float c;
float a=1;
float b=3;
	
	if(FN(a)*FN(b) >=0.0){
		printf("Check your a and b");
		return 0;
		}
	while(fabs(b-a)>=0.000001){
		c = (a+b)/2;
		if(FN(c)==0.0){
			printf("The root of the function is %f\n",c);
			break;
		}
		else if (FN(a)*FN(c)>0){
			//printf("The root of the function is %f\n",c);
			a=c;
			}
		else if (FN(b)*FN(c)>0){
			//printf("The root of the function is %f\n",c); 
                        b=c; 
                        } 
 			}
		printf("The root of the function is %f\n",c);





}
