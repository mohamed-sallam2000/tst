


/**************************************
*file name:nvic program.c
*date:2/9/2022
*made by:mohamed sallam
***************************************/

#include "STD_TYPES.h"
#include "Macros.h"
#include "NVIC_private.h"
#include "NVIC_INTERFACE.h"




void NVIC_disable_interrupt(u8 int_ID){


 if(int_ID<=31){(NVIC_clear_INT0=1<<int_ID);	}
else if(int_ID<=63){(NVIC_clear_INT1=1<<(int_ID-32));}


}
/*****************************************************/
void NVIC_set_pending_flag_interrupt(u8 int_ID){


 if(int_ID<=31){(NVIC_set_pinding_INT0=1<<int_ID);	}
else if(int_ID<=63){(NVIC_set_pinding_INT1=1<<(int_ID-32));}


}

void NVIC_clear_pending_flag_interrupt(u8 int_ID){
	
	
	


 if(int_ID<=31){(NVIC_clear_pinding_INT0=1<<int_ID);	}
else if(int_ID<=63){(NVIC_clear_pinding_INT1=1<<(int_ID-32));}


     }



/************************************************************/

u8 NVIC_get_active_bit_interrupt(  u8 int_ID){
u8 result=0;


 if(int_ID<=31){result=  GET_BIT(NVIC_active_bit_INT0,int_ID);	}
else if(int_ID<=63){result=  GET_BIT(NVIC_active_bit_INT1,int_ID);}

return result;
     }
/*************************************************************/
void NVIC_SET_priorty(s8 copy_s8_intID ,u8 copy_u8Gropu,u8 copy_sub,u32 copy_groupforming){
u8 local_poriorty_value=(copy_sub|(copy_u8Gropu<<(copy_groupforming -g1_8group_1sub)/256));
APINT=copy_groupforming;
	
if(copy_s8_intID>=0){}
NVIC_PIR_ptr[copy_s8_intID]=(local_poriorty_value<<5);
	
}
/*************************************************************/
void NVIC_en_int_id(u8 int_ID){

 if(int_ID<=31){(NVIC_ENEBLE_INT0=1<<int_ID);	}
else if(int_ID<=63){(NVIC_ENEBLE_INT1=1<<(int_ID-32));}


}




 

