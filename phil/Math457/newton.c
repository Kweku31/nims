#include<stdio.h>
#include<math.h>

#define FN(x) ((x*x*x)-x-1)
#define DV(x) (3*x*x -1)
int main(){
float c;
float p=1;
float q;
	while(fabs(FN(q))>=0.000001){
	q = p - (FN(p)/DV(p));
	p = q;
	if(DV(p) == 0){
	printf("Error\n");
	} 
	}
	printf("The root of the function is %f\n",q);
}

